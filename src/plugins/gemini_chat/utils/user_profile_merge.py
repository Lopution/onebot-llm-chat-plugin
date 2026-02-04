# 用户档案合并逻辑
"""
实现 LLM 抽取结果与现有档案的合并策略。

核心原则：
1. 不覆盖原则：已有值非空时，需要更高置信度才能替换
2. 稳定性原则：易变字段需要更高门槛
3. 可追溯原则：记录 evidence、confidence、来源
4. 二次确认：覆盖旧值需要同一新值重复出现
"""

import json
import re
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from nonebot import logger as log


def normalize_text(text: str) -> str:
    """标准化文本（用于比较）
    
    - 全角转半角
    - 去除首尾空白
    - 统一大小写
    """
    if not text:
        return ""
    
    # 全角转半角
    result = ""
    for char in text:
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:
            result += chr(code - 0xFEE0)
        elif code == 0x3000:
            result += " "
        else:
            result += char
    
    return result.strip().lower()


def texts_equal(a: str, b: str) -> bool:
    """判断两个文本是否等价（标准化后比较）"""
    return normalize_text(a) == normalize_text(b)


def merge_list_field(
    existing: List[str],
    add: List[str],
    remove: List[str]
) -> List[str]:
    """合并列表字段（preferences/dislikes）
    
    Args:
        existing: 现有列表
        add: 要添加的项
        remove: 要移除的项
        
    Returns:
        合并后的列表（去重）
    """
    if not existing:
        existing = []
    
    # 标准化现有列表
    existing_normalized = {normalize_text(x): x for x in existing}
    
    # 添加新项
    for item in add:
        normalized = normalize_text(item)
        if normalized and normalized not in existing_normalized:
            existing_normalized[normalized] = item
    
    # 移除项
    for item in remove:
        normalized = normalize_text(item)
        if normalized in existing_normalized:
            del existing_normalized[normalized]
    
    return list(existing_normalized.values())


class ProfileMergeResult:
    """合并结果"""
    
    def __init__(self):
        self.merged_fields: Dict[str, Any] = {}  # 实际要写入的字段
        self.pending_fields: Dict[str, Any] = {}  # 待二次确认的字段
        self.skipped_fields: Dict[str, str] = {}  # 跳过的字段及原因
        self.provenance: Dict[str, Any] = {}  # 溯源信息
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "merged_fields": self.merged_fields,
            "pending_fields": self.pending_fields,
            "skipped_fields": self.skipped_fields,
            "provenance": self.provenance
        }


def merge_profile_delta(
    existing_profile: Dict[str, Any],
    delta: Dict[str, Any],
    evidence: Dict[str, Any],
    confidence: Dict[str, float],
    pending_overrides: Dict[str, Any],
    threshold_new: float = 0.6,
    threshold_override: float = 0.85,
    require_repeat: bool = True,
    extractor_model: str = "unknown"
) -> Tuple[ProfileMergeResult, Dict[str, Any]]:
    """合并 LLM 抽取的 delta 到现有档案
    
    Args:
        existing_profile: 现有档案（从数据库读取）
        delta: LLM 输出的 delta 字段
        evidence: 证据信息
        confidence: 置信度信息
        pending_overrides: 上次待确认的覆盖（用于二次确认）
        threshold_new: 新字段写入的最低置信度
        threshold_override: 覆盖旧值的最低置信度
        require_repeat: 是否需要二次确认才能覆盖
        extractor_model: 抽取模型名称
        
    Returns:
        (ProfileMergeResult, new_pending_overrides)
    """
    result = ProfileMergeResult()
    new_pending = {}
    
    # 标量字段列表
    scalar_fields = ["nickname", "real_name", "identity", "occupation", "age", "location", "birthday"]
    # 列表字段
    list_fields = ["preferences", "dislikes"]
    
    now = datetime.now().isoformat()
    
    # 处理标量字段
    for field in scalar_fields:
        new_value = delta.get(field)
        if new_value is None:
            continue
            
        # 获取置信度
        field_confidence = confidence.get(field, 0.0)
        existing_value = existing_profile.get(field)
        
        # 构建溯源信息
        provenance_info = {
            "value": new_value,
            "confidence": field_confidence,
            "quote": evidence.get(field, {}).get("quote", ""),
            "message_ids": evidence.get(field, {}).get("message_ids", []),
            "model": extractor_model,
            "updated_at": now
        }
        
        if not existing_value:
            # 旧值为空：检查置信度门槛
            if field_confidence >= threshold_new:
                result.merged_fields[field] = new_value
                result.provenance[field] = provenance_info
                log.debug(f"[ProfileMerge] 新字段写入 | field={field} | value={new_value} | conf={field_confidence:.2f}")
            else:
                result.skipped_fields[field] = f"置信度不足 ({field_confidence:.2f} < {threshold_new})"
        else:
            # 旧值非空
            if texts_equal(str(existing_value), str(new_value)):
                # 值相同，仅更新溯源（可选）
                result.provenance[field] = provenance_info
                result.skipped_fields[field] = "值相同，仅更新溯源"
            else:
                # 值不同，需要检查覆盖条件
                if field_confidence < threshold_override:
                    result.skipped_fields[field] = f"置信度不足以覆盖 ({field_confidence:.2f} < {threshold_override})"
                    continue
                
                if require_repeat:
                    # 检查是否二次确认
                    pending_value = pending_overrides.get(field)
                    if pending_value is not None and texts_equal(str(pending_value), str(new_value)):
                        # 二次确认通过
                        result.merged_fields[field] = new_value
                        result.provenance[field] = provenance_info
                        log.info(f"[ProfileMerge] 二次确认覆盖 | field={field} | old={existing_value} | new={new_value}")
                    else:
                        # 首次出现，记入待确认
                        result.pending_fields[field] = new_value
                        new_pending[field] = new_value
                        result.skipped_fields[field] = "待二次确认"
                        log.debug(f"[ProfileMerge] 待二次确认 | field={field} | old={existing_value} | new={new_value}")
                else:
                    # 不需要二次确认，直接覆盖
                    result.merged_fields[field] = new_value
                    result.provenance[field] = provenance_info
                    log.info(f"[ProfileMerge] 直接覆盖 | field={field} | old={existing_value} | new={new_value}")
    
    # 处理列表字段
    for field in list_fields:
        field_delta = delta.get(field)
        if field_delta is None:
            continue
        
        add_items = field_delta.get("add", [])
        remove_items = field_delta.get("remove", [])
        
        if not add_items and not remove_items:
            continue
        
        field_confidence = confidence.get(field, 0.0)
        
        # 列表字段使用较低门槛（因为是增量操作）
        if field_confidence < threshold_new:
            result.skipped_fields[field] = f"置信度不足 ({field_confidence:.2f} < {threshold_new})"
            continue
        
        # 获取现有列表
        existing_list = existing_profile.get(field, [])
        if isinstance(existing_list, str):
            try:
                existing_list = json.loads(existing_list) if existing_list else []
            except json.JSONDecodeError:
                existing_list = []
        
        # 合并
        merged_list = merge_list_field(existing_list, add_items, remove_items)
        
        if merged_list != existing_list:
            result.merged_fields[field] = json.dumps(merged_list, ensure_ascii=False)
            result.provenance[field] = {
                "added": add_items,
                "removed": remove_items,
                "confidence": field_confidence,
                "quote": evidence.get(field, {}).get("quote", ""),
                "message_ids": evidence.get(field, {}).get("message_ids", []),
                "model": extractor_model,
                "updated_at": now
            }
            log.debug(f"[ProfileMerge] 列表更新 | field={field} | +{len(add_items)} -{len(remove_items)}")
    
    return result, new_pending


def build_provenance_extra_info(
    existing_extra_info: Dict[str, Any],
    new_provenance: Dict[str, Any]
) -> Dict[str, Any]:
    """构建包含溯源信息的 extra_info
    
    Args:
        existing_extra_info: 现有的 extra_info
        new_provenance: 新的溯源信息
        
    Returns:
        合并后的 extra_info
    """
    if not existing_extra_info:
        existing_extra_info = {}
    
    # 确保 profile_provenance 存在
    if "profile_provenance" not in existing_extra_info:
        existing_extra_info["profile_provenance"] = {}
    
    # 更新各字段的溯源
    for field, prov in new_provenance.items():
        existing_extra_info["profile_provenance"][field] = prov
    
    return existing_extra_info
