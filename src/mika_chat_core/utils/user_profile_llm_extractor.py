"""用户档案 LLM 抽取器。

调用 LLM 从用户消息中抽取档案信息（姓名、身份、偏好等）。

设计原则：
- 不污染主对话上下文（直接调用 API，不经过 MikaClient.chat）
- 使用快速模型降低成本
- 强制 JSON 输出格式
- 健壮的 JSON 解析（支持多种格式容错）

相关模块：
- [`user_profile_extract_service`](user_profile_extract_service.py:1): 异步抽取服务
- [`user_profile_merge`](user_profile_merge.py:1): 档案合并逻辑
"""

import json
import re
import httpx
from typing import Dict, Any, Optional, List
from datetime import datetime

from ..infra.logging import logger as log

from ..config import plugin_config
from ..mika_api_layers.core.proactive import extract_json_object
from ..llm.providers import (
    build_provider_request,
    detect_provider_name,
    get_provider_capabilities,
    parse_provider_response,
)
from ..utils.prompt_loader import load_prompt_yaml


# ==================== Magic-number constants ====================
PROFILE_EXTRACT_PROMPT_FILE = "profile_extract.yaml"

MESSAGE_FALLBACK_ID_PREFIX = "msg_"
MESSAGE_CONTENT_PREVIEW_CHARS = 200

HTTP_CLIENT_TIMEOUT_SECONDS = 30.0
RAW_RESPONSE_ERROR_PREVIEW_CHARS = 500
RAW_RESPONSE_PARSE_ERROR_PREVIEW_CHARS = 200
RAW_RESPONSE_RESULT_PREVIEW_CHARS = 1000

# 缓存提示词配置
_prompt_config_cache: Optional[Dict[str, Any]] = None


def safe_parse_json(raw: str) -> Dict[str, Any]:
    """健壮的 JSON 解析，处理常见的 LLM 输出问题
    
    处理：
    - Markdown 代码块包裹（```json ... ```）
    - 尾随逗号（,} 或 ,]）
    - 截断的 JSON（补全缺失的括号）
    
    Args:
        raw: 原始 JSON 字符串
        
    Returns:
        解析后的字典
        
    Raises:
        json.JSONDecodeError: 如果无法解析
    """
    # 1. 清理 Markdown 代码块
    clean = re.sub(r'^```(?:json)?\s*', '', raw.strip())
    clean = re.sub(r'```\s*$', '', clean)
    clean = clean.strip()
    
    # 2. 尝试提取 JSON 对象（如果有前导/尾随文本）
    extracted = extract_json_object(clean)
    if extracted:
        clean = extracted
    
    # 3. 移除尾随逗号（,} → } 和 ,] → ]）
    clean = re.sub(r',(\s*[}\]])', r'\1', clean)
    
    # 4. 尝试补全截断的 JSON
    open_braces = clean.count('{') - clean.count('}')
    open_brackets = clean.count('[') - clean.count(']')
    if open_braces > 0 or open_brackets > 0:
        # 移除末尾可能残留的逗号和空白
        clean = clean.rstrip(',\n\t ')
        # 补全缺失的括号
        clean += '}' * open_braces + ']' * open_brackets
    
    return json.loads(clean)


def load_profile_extract_prompt() -> Dict[str, Any]:
    """加载档案抽取提示词配置"""
    global _prompt_config_cache
    if _prompt_config_cache is None:
        _prompt_config_cache = load_prompt_yaml(PROFILE_EXTRACT_PROMPT_FILE)
    return _prompt_config_cache


def format_existing_profile(profile: Dict[str, Any]) -> str:
    """格式化现有档案为可读字符串"""
    if not profile:
        return "（无现有档案）"
    
    parts = []
    field_names = {
        "nickname": "昵称",
        "real_name": "真名",
        "identity": "身份/关系",
        "occupation": "职业",
        "age": "年龄",
        "location": "位置",
        "birthday": "生日",
        "preferences": "喜好",
        "dislikes": "不喜欢"
    }
    
    for field, label in field_names.items():
        value = profile.get(field)
        if value:
            if isinstance(value, list):
                value = ", ".join(value)
            elif isinstance(value, str) and value.startswith("["):
                try:
                    value = ", ".join(json.loads(value))
                except:
                    pass
            parts.append(f"- {label}: {value}")
    
    return "\n".join(parts) if parts else "（无现有档案）"


def format_messages(messages: List[Dict[str, Any]]) -> str:
    """格式化消息列表为可读字符串
    
    Args:
        messages: 消息列表，每条消息包含 content, message_id, timestamp 等
        
    Returns:
        格式化的字符串
    """
    if not messages:
        return "（无消息）"
    
    lines = []
    for i, msg in enumerate(messages, 1):
        content = msg.get("content", "")
        msg_id = msg.get("message_id", f"{MESSAGE_FALLBACK_ID_PREFIX}{i}")
        
        # 如果是多模态内容，提取文本部分
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            content = " ".join(text_parts)
        
        # 截断过长内容
        if len(content) > MESSAGE_CONTENT_PREVIEW_CHARS:
            content = content[:MESSAGE_CONTENT_PREVIEW_CHARS] + "..."
        
        lines.append(f"[{msg_id}] {content}")
    
    return "\n".join(lines)


class ProfileExtractResult:
    """抽取结果"""
    
    def __init__(
        self,
        success: bool,
        no_update: bool = True,
        delta: Optional[Dict[str, Any]] = None,
        evidence: Optional[Dict[str, Any]] = None,
        confidence: Optional[Dict[str, float]] = None,
        notes: str = "",
        raw_response: str = "",
        error: str = ""
    ):
        self.success = success
        self.no_update = no_update
        self.delta = delta or {}
        self.evidence = evidence or {}
        self.confidence = confidence or {}
        self.notes = notes
        self.raw_response = raw_response
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "no_update": self.no_update,
            "delta": self.delta,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "notes": self.notes,
            "error": self.error
        }


async def extract_profile_with_llm(
    platform_user_id: str,
    nickname: str,
    messages: List[Dict[str, Any]],
    existing_profile: Dict[str, Any],
    group_id: Optional[str] = None,
    api_key: Optional[str] = None,
    http_client: Optional[httpx.AsyncClient] = None
) -> ProfileExtractResult:
    """使用 LLM 从消息中抽取用户档案信息
    
    Args:
        platform_user_id: 平台用户ID
        nickname: 用户昵称
        messages: 该用户最近的消息列表
        existing_profile: 现有档案
        group_id: 群组 ID（可选）
        api_key: API Key（可选，默认从配置获取）
        http_client: HTTP 客户端（可选，默认创建新的）
        
    Returns:
        ProfileExtractResult
    """
    # 加载提示词
    prompt_config = load_profile_extract_prompt()
    if not prompt_config:
        return ProfileExtractResult(
            success=False,
            error="无法加载提示词配置"
        )
    
    extract_config = prompt_config.get("profile_extract", {})
    system_prompt = extract_config.get("system", "")
    template = extract_config.get("template", "")
    
    if not template:
        return ProfileExtractResult(
            success=False,
            error="提示词模板为空"
        )
    
    # 格式化输入
    existing_profile_str = format_existing_profile(existing_profile)
    messages_str = format_messages(messages)
    scene = "群聊" if group_id else "私聊"
    
    # 构建用户消息
    user_prompt = template.format(
        existing_profile=existing_profile_str,
        platform_user_id=platform_user_id,
        nickname=nickname,
        scene=scene,
        messages=messages_str
    )
    
    # 获取 API 配置
    if not api_key:
        if plugin_config.llm_api_key_list:
            api_key = plugin_config.llm_api_key_list[0]
        else:
            api_key = plugin_config.llm_api_key
    
    model = plugin_config.profile_extract_model or plugin_config.llm_fast_model
    temperature = plugin_config.profile_extract_temperature
    max_tokens = plugin_config.profile_extract_max_tokens
    llm_cfg = plugin_config.get_llm_config()
    base_url = str(llm_cfg.get("base_url") or plugin_config.llm_base_url)
    provider_name = detect_provider_name(
        configured_provider=str(llm_cfg.get("provider") or "openai_compat"),
        base_url=base_url,
    )
    provider_capabilities = get_provider_capabilities(
        configured_provider=provider_name,
        base_url=base_url,
        model=model,
    )
    
    # 构建请求
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False
    }
    if provider_capabilities.supports_json_object_response:
        request_body["response_format"] = {"type": "json_object"}
    
    # 发送请求
    should_close_client = False
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=HTTP_CLIENT_TIMEOUT_SECONDS)
        should_close_client = True
    
    raw_response = ""
    
    try:
        if plugin_config.profile_extract_log_payload:
            log.debug(f"[ProfileExtract] 请求 | model={model} | messages={len(messages)}")
        
        prepared = build_provider_request(
            provider=provider_name,
            base_url=base_url,
            model=model,
            api_key=api_key,
            request_body=request_body,
            extra_headers=dict(llm_cfg.get("extra_headers") or {}),
            default_temperature=float(temperature),
        )
        response = await http_client.post(
            prepared.url,
            headers=prepared.headers,
            params=prepared.params,
            json=prepared.json_body,
        )
        
        response.raise_for_status()
        data = response.json()
        
        # 提取内容
        if provider_name == "openai_compat":
            raw_response = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            finish_reason = data.get("choices", [{}])[0].get("finish_reason", "UNKNOWN")
        else:
            assistant_message, _tool_calls, parsed_content, parsed_finish_reason = parse_provider_response(
                provider=provider_name,
                data=data,
            )
            raw_response = (
                str(parsed_content)
                if parsed_content is not None
                else str(assistant_message.get("content") or "")
            )
            finish_reason = parsed_finish_reason or "UNKNOWN"
        
        if not raw_response or not raw_response.strip():
            log.warning(f"[ProfileExtract] API 返回空内容 | finish_reason={finish_reason}")
            return ProfileExtractResult(
                success=False,
                error=f"API 返回空内容 (finish_reason={finish_reason})",
                raw_response=str(data)[:RAW_RESPONSE_ERROR_PREVIEW_CHARS]
            )
        
        # 使用健壮的 JSON 解析
        result_data = safe_parse_json(raw_response)
        
        # 验证结构
        if not isinstance(result_data, dict):
            return ProfileExtractResult(
                success=False,
                error="返回格式不是对象",
                raw_response=raw_response[:RAW_RESPONSE_ERROR_PREVIEW_CHARS]
            )
        
        no_update = result_data.get("no_update", True)
        delta = result_data.get("delta", {})
        evidence = result_data.get("evidence", {})
        confidence = result_data.get("confidence", {})
        notes = result_data.get("notes", "")
        
        if plugin_config.profile_extract_log_payload:
            log.debug(f"[ProfileExtract] 结果 | no_update={no_update} | delta_keys={list(delta.keys())}")
        
        return ProfileExtractResult(
            success=True,
            no_update=no_update,
            delta=delta,
            evidence=evidence,
            confidence=confidence,
            notes=notes,
            raw_response=raw_response[:RAW_RESPONSE_RESULT_PREVIEW_CHARS]
        )
        
    except json.JSONDecodeError as e:
        log.error(
            f"[ProfileExtract] JSON 解析失败: {e} | raw={raw_response[:RAW_RESPONSE_PARSE_ERROR_PREVIEW_CHARS]}"
        )
        return ProfileExtractResult(
            success=False,
            error=f"JSON 解析失败: {e}",
            raw_response=raw_response[:RAW_RESPONSE_ERROR_PREVIEW_CHARS]
        )
    except httpx.HTTPStatusError as e:
        log.error(f"[ProfileExtract] HTTP 错误: {e.response.status_code}")
        return ProfileExtractResult(
            success=False,
            error=f"HTTP {e.response.status_code}",
            raw_response=str(e.response.text)[:RAW_RESPONSE_ERROR_PREVIEW_CHARS]
        )
    except httpx.TimeoutException:
        log.warning("[ProfileExtract] 请求超时")
        return ProfileExtractResult(
            success=False,
            error="请求超时"
        )
    except Exception as e:
        log.error(f"[ProfileExtract] 未知错误: {repr(e)}")
        return ProfileExtractResult(
            success=False,
            error=str(e)
        )
    finally:
        if should_close_client and http_client:
            await http_client.aclose()
