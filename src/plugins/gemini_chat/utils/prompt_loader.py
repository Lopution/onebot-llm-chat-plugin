# 系统提示词加载器
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from nonebot import logger

# 默认提示词目录

# 默认提示词目录
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
SEARCH_PROMPT_FILE = "search.yaml"
JUDGE_PROMPT_FILE = "proactive_judge.yaml"


def load_prompt_yaml(filename: str = "mika.yaml") -> Dict[str, Any]:
    """加载 YAML 格式的提示词配置"""

    # [安全] 限制 prompt 文件名只能是 prompts 目录下的文件名，禁止路径/.. 穿越。
    # 允许的后缀：.yaml / .yml
    try:
        if not filename or not isinstance(filename, str):
            logger.warning(f"[PromptLoader] Invalid prompt filename: {filename!r}")
            return {}

        # 禁止任意路径分隔符（跨平台）
        if "/" in filename or "\\" in filename:
            logger.warning(f"[PromptLoader] Unsafe prompt filename (path separator): {filename!r}")
            return {}

        # 禁止 ..（保守策略）
        if ".." in filename:
            logger.warning(f"[PromptLoader] Unsafe prompt filename ('..'): {filename!r}")
            return {}

        lower = filename.lower()
        if not (lower.endswith(".yaml") or lower.endswith(".yml")):
            logger.warning(f"[PromptLoader] Unsafe prompt filename (extension): {filename!r}")
            return {}
    except Exception as e:
        logger.warning(f"[PromptLoader] Prompt filename validation failed: {e}")
        return {}

    filepath = PROMPTS_DIR / filename
    
    if not filepath.exists():
        logger.warning(f"[PromptLoader] Prompt file not found: {filepath}")
        return {}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            logger.success(f"[PromptLoader] Loaded prompt from: {filename}")
            return data or {}
    except yaml.YAMLError as e:
        logger.error(f"[PromptLoader] Failed to parse YAML: {e}")
        return {}
    except Exception as e:
        logger.error(f"[PromptLoader] Failed to load prompt: {e}")
        return {}


def _normalize_legacy_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """兼容旧 tests 的 prompt config 结构。

    历史测试使用：social / language_style / interaction_rules。
    当前实现使用：role / personality / style / instructions / environment。
    这里做 best-effort 映射，确保旧字段内容能出现在最终 prompt 中。
    """
    if not config:
        return config

    cfg = dict(config)

    # language_style -> style
    if "language_style" in cfg and "style" not in cfg:
        ls = cfg.get("language_style") or {}
        style: Dict[str, Any] = {}
        if ls.get("jk_style"):
            style["tone"] = ls.get("jk_style")
        if ls.get("expressions"):
            style["particles"] = {
                "description": "常用语气词",
                "list": list(ls.get("expressions") or []),
            }
        if ls.get("forbidden"):
            style["forbidden"] = list(ls.get("forbidden") or [])
        cfg["style"] = style

    # interaction_rules -> instructions
    if "interaction_rules" in cfg and "instructions" not in cfg:
        ir = cfg.get("interaction_rules") or {}
        cfg["instructions"] = {
            "scene_adaptation": {
                "group_chat": list(ir.get("group_chat") or []),
            },
            "knowledge_base": list(ir.get("knowledge") or []),
            "conversation_context": list(ir.get("context") or []),
        }

    # social -> personality (best-effort)
    if "social" in cfg and "personality" not in cfg:
        social = cfg.get("social") or {}
        loves = list(social.get("love") or [])
        friends = list(social.get("friends") or [])
        core = []
        if loves:
            core.append({"trait": "喜好", "description": "、".join(loves)})
        if friends:
            core.append({
                "trait": "朋友",
                "description": "；".join([
                    f"{x.get('name','')}({x.get('trait','')})" for x in friends
                ]),
            })
        cfg["personality"] = {"core": core}

    return cfg


def generate_system_prompt(
    config: Dict[str, Any], 
    master_name: str = "Sensei",
    current_date: str = ""
) -> str:
    """从 YAML 配置生成系统提示词"""
    
    if not config:
        return "你是一个友好的AI助手"

    # 兼容旧结构字段（tests 仍在使用 social / language_style / interaction_rules）
    config = _normalize_legacy_config(config)
    
    parts = []
    
    # 1. 角色信息 (Role)
    role = config.get("role", {})
    if role:
        parts.append(f"# Role: {role.get('name', '')} ({role.get('name_en', '')})")
        if role.get("identity"):
            parts.append(f"- **身份**：{role['identity']}")
    
    # 2. 性格特征 (Personality)
    personality = config.get("personality", {})
    if personality.get("core"):
        parts.append("\n## Personality")
        for trait in personality["core"]:
            parts.append(f"- **{trait.get('trait', '')}**：{trait.get('description', '')}")
    
    # 3. 人际关系 (Relationships) - 使用 role.senseis 统一结构
    role_senseis = config.get("role", {}).get("senseis", {})
    if role_senseis:
        parts.append("\n## Relationships & Attitude")
        parts.append(f"- **Target**: {role_senseis.get('target', 'All Users')}")
        parts.append(f"- **Attitude**: {role_senseis.get('attitude', '')}")
        if role_senseis.get("rules"):
            for rule in role_senseis["rules"]:
                parts.append(f"- {rule}")
    
    # 4. 语言风格 (Style)
    style = config.get("style", {})
    if style:
        parts.append("\n## Language Style")
        if style.get("tone"):
            parts.append(f"- **Tone**: {style['tone']}")
        if style.get("length"):
            parts.append(f"- **Length**: {style['length']}")
        
        particles = style.get("particles", {})
        if particles.get("list"):
            parts.append(f"- **Particles**: {particles.get('description', '')} {', '.join(particles['list'])}")
        
        if style.get("forbidden"):
            parts.append("- **Forbidden**:")
            for rule in style["forbidden"]:
                parts.append(f"    - {rule}")
    
    # 5. 技术指令 (Instructions)
    instructions = config.get("instructions", {})
    if instructions:
        parts.append("\n## System Instructions (Critical)")
        
        instruction_index = 1
        
        if instructions.get("context_awareness"):
            parts.append(f"{instruction_index}. **Context Awareness**:")
            for rule in instructions["context_awareness"]:
                parts.append(f"    - {rule}")
            instruction_index += 1
        
        if instructions.get("time_awareness"):
            parts.append(f"{instruction_index}. **Time Awareness**:")
            for rule in instructions["time_awareness"]:
                parts.append(f"    - {rule}")
            instruction_index += 1
        
        if instructions.get("reply_handling"):
            parts.append(f"{instruction_index}. **Reply Handling**:")
            for rule in instructions["reply_handling"]:
                parts.append(f"    - {rule}")
            instruction_index += 1
        
        if instructions.get("image_handling"):
            parts.append(f"{instruction_index}. **Image Handling**:")
            for rule in instructions["image_handling"]:
                parts.append(f"    - {rule}")
            instruction_index += 1
        
        if instructions.get("response_length"):
            parts.append(f"{instruction_index}. **Response Length**:")
            for rule in instructions["response_length"]:
                parts.append(f"    - {rule}")
            instruction_index += 1
        
        if instructions.get("conversation_context"):
            parts.append(f"{instruction_index}. **Conversation Context**:")
            for rule in instructions["conversation_context"]:
                parts.append(f"    - {rule}")
            instruction_index += 1
        
        if instructions.get("scene_adaptation"):
            parts.append(f"{instruction_index}. **Scene Adaptation**:")
            scene = instructions["scene_adaptation"]
            if scene.get("private_chat"):
                parts.append("    - **Private Chat**:")
                for rule in scene["private_chat"]:
                    parts.append(f"        - {rule}")
            if scene.get("group_chat"):
                parts.append("    - **Group Chat**:")
                for rule in scene["group_chat"]:
                    parts.append(f"        - {rule}")
            instruction_index += 1
        
        if instructions.get("serious_qa"):
            parts.append(f"{instruction_index}. **Serious Q&A Strategy**:")
            for rule in instructions["serious_qa"]:
                parts.append(f"    - {rule}")
            instruction_index += 1
        
        if instructions.get("knowledge_base"):
            parts.append(f"{instruction_index}. **Knowledge & Search**:")
            for rule in instructions["knowledge_base"]:
                parts.append(f"    - {rule}")
            instruction_index += 1
        
        if instructions.get("security_protocols"):
            parts.append(f"{instruction_index}. **Security Protocols**:")
            for rule in instructions["security_protocols"]:
                parts.append(f"    - {rule}")
            instruction_index += 1

    # 6. 环境信息
    # tests 期望 system prompt 中包含 current_date（支持自定义日期/自动日期）。
    # 生产侧仍可在 build_messages() 里做更细的动态注入；这里保留静态 Date 字段以满足单测。
    env = config.get("environment", {})
    parts.append("\n## Environment")
    parts.append(f"- **Date**: {current_date}")
    if env.get("master_info"):
        parts.append(f"- **Master Info**: {env['master_info']}")
    
    # 7. Few-Shot Examples
    examples = config.get("dialogue_examples", [])
    if examples:
        parts.append("\n## Dialogue Examples (Few-Shot)")
        for ex in examples:
            parts.append(f"\n**{ex.get('scenario', 'Case')}**")
            parts.append(f"User: {ex.get('user', '')}")
            parts.append(f"Mika: {ex.get('bot', '')}")
    
    prompt = "\n".join(parts)
    
    # 替换变量
    prompt = prompt.replace("{master_name}", master_name)
    prompt = prompt.replace("{current_date}", current_date)
    
    return prompt


def get_system_prompt(
    prompt_file: str = "system.yaml",
    master_name: str = "Sensei",
    current_date: Optional[str] = None
) -> str:
    """获取系统提示词（主入口函数）"""
    from datetime import datetime
    
    if current_date is None:
        current_date = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    
    config = load_prompt_yaml(prompt_file)
    return generate_system_prompt(config, master_name, current_date)


def load_error_messages(prompt_file: str = "system.yaml") -> Dict[str, str]:
    """
    从 YAML 配置中加载错误消息模板
    
    Args:
        prompt_file: 提示词配置文件名
        
    Returns:
        错误消息字典，如未找到则返回空字典
    """
    config = load_prompt_yaml(prompt_file)
    error_messages = config.get("error_messages", {})
    
    if error_messages:
        logger.debug(f"[PromptLoader] 已加载 {len(error_messages)} 条错误消息模板")
    
    return error_messages


def get_character_name(prompt_file: str = "system.yaml") -> str:
    """
    从 YAML 配置中获取角色名称
    
    Args:
        prompt_file: 提示词配置文件名
        
    Returns:
        角色名称，默认为 "助手"
    """
    config = load_prompt_yaml(prompt_file)
    role = config.get("role", {})
    name = role.get("name", "助手")
    
    logger.debug(f"[PromptLoader] 角色名称: {name}")
    return name


def load_search_prompt() -> Dict[str, Any]:
    """
    加载搜索相关的提示词配置
    
    Returns:
        搜索提示词配置字典
    """
    config = load_prompt_yaml(SEARCH_PROMPT_FILE)
    return config


def load_judge_prompt() -> Dict[str, Any]:
    """
    加载主动发言判决提示词配置
    
    Returns:
        判决提示词配置字典
    """
    config = load_prompt_yaml(JUDGE_PROMPT_FILE)
    return config
