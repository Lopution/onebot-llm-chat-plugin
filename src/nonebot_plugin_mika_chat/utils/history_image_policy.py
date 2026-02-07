"""历史图片上下文增强策略模块。

实现 hybrid 策略，智能决定是否需要历史图片辅助理解：
- 规则判定是否需要历史图片
- 决定使用 inline 回注还是 two-stage 补图
- 支持连续图片拼图

策略流程：
1. 检查 mode 配置 (off/inline/two_stage/hybrid)
2. 从 ImageCache 获取候选图片 (peek_recent_images)
3. 根据消息内容判定需求强度
4. 输出决策结果供 handlers/build_messages 使用

相关模块：
- [`image_cache_core`](image_cache_core.py:1): 图片缓存
- [`image_collage`](image_collage.py:1): 多图拼接
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any

from nonebot import logger as log

from .image_cache_core import CachedImage


class HistoryImageAction(Enum):
    """历史图片处理动作"""
    NONE = "none"           # 不注入历史图片
    INLINE = "inline"       # 直接回注原图
    TWO_STAGE = "two_stage" # 两阶段补图（工具调用）
    COLLAGE = "collage"     # 拼图后注入


@dataclass
class HistoryImageDecision:
    """历史图片策略决策结果"""
    action: HistoryImageAction
    # 需要注入的图片列表 (对于 INLINE/COLLAGE)
    images_to_inject: List[CachedImage] = field(default_factory=list)
    # 候选 msg_ids (对于 TWO_STAGE，模型可请求这些图片)
    candidate_msg_ids: List[str] = field(default_factory=list)
    # 判定原因（用于日志/调试）
    reason: str = ""
    # 触发强度 (0.0-1.0)，用于未来扩展
    confidence: float = 0.0


# 强指代关键词（高置信需要历史图片）
STRONG_REFERENCE_KEYWORDS = [
    "上一张", "上张", "刚才那张", "刚才的图", "刚发的",
    "之前那张", "之前的图", "那张图", "那个图",
    "这个表情包", "这表情", "那个表情包", "那表情",
    "上一个", "上个", "刚才那个",
]

# 对比/多图关键词（可能需要多张图片）
COMPARISON_KEYWORDS = [
    "对比", "比较", "区别", "不同", "一样吗", "相同吗",
    "上上张", "前几张", "这两张", "这几张",
    "哪个", "哪张", "哪一个", "哪一张",
    "找不同", "找茬", "区分",
]

# 一般图片指代关键词（中等置信）
GENERAL_IMAGE_KEYWORDS = [
    "这张图", "这个图", "这图", "图片", "图中", "图里",
    "照片", "截图", "表情包", "meme",
    "看看", "帮我看", "识别", "分析",
]


def _has_any_keyword(text: str, keywords: List[str]) -> bool:
    """检查文本是否包含任一关键词"""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def _count_image_placeholders_in_context(context_messages: List[Dict[str, Any]], lookback: int = 5) -> int:
    """统计最近上下文中图片占位符数量"""
    count = 0
    for msg in context_messages[-lookback:]:
        content = msg.get("content", "")
        if isinstance(content, str):
            count += content.count("[图片")
    return count


def determine_history_image_action(
    message_text: str,
    candidate_images: List[CachedImage],
    context_messages: Optional[List[Dict[str, Any]]] = None,
    mode: str = "hybrid",
    inline_max: int = 1,
    two_stage_max: int = 2,
    collage_max: int = 4,
    enable_collage: bool = True,
    custom_keywords: Optional[List[str]] = None,
) -> HistoryImageDecision:
    """判定历史图片处理策略
    
    Args:
        message_text: 当前用户消息文本
        candidate_images: 候选图片列表（来自 ImageCache.peek_recent_images）
        context_messages: 历史上下文消息列表（可选，用于判断对话形态）
        mode: 处理模式 (off/inline/two_stage/hybrid)
        inline_max: inline 最多注入几张
        two_stage_max: two-stage 最多补几张
        collage_max: 拼图最多合成几张
        enable_collage: 是否启用拼图
        custom_keywords: 自定义触发关键词（可选）
        
    Returns:
        HistoryImageDecision 决策结果
    """
    # 模式检查
    if mode == "off":
        return HistoryImageDecision(
            action=HistoryImageAction.NONE,
            reason="mode=off"
        )
    
    # 没有候选图片
    if not candidate_images:
        return HistoryImageDecision(
            action=HistoryImageAction.NONE,
            reason="no_candidate_images"
        )
    
    # 合并关键词
    all_keywords = custom_keywords or []
    if not all_keywords:
        all_keywords = STRONG_REFERENCE_KEYWORDS + COMPARISON_KEYWORDS + GENERAL_IMAGE_KEYWORDS
    
    # 判定触发强度
    has_strong_ref = _has_any_keyword(message_text, STRONG_REFERENCE_KEYWORDS)
    has_comparison = _has_any_keyword(message_text, COMPARISON_KEYWORDS)
    has_general_ref = _has_any_keyword(message_text, GENERAL_IMAGE_KEYWORDS)
    
    # 检查上下文中是否有图片占位符
    context_has_images = False
    if context_messages:
        context_has_images = _count_image_placeholders_in_context(context_messages) > 0
    
    # 计算置信度
    confidence = 0.0
    if has_strong_ref:
        confidence = 0.9
    elif has_comparison:
        confidence = 0.8
    elif has_general_ref:
        confidence = 0.6
    elif context_has_images:
        confidence = 0.3
    
    # 无明确触发信号
    if confidence < 0.3:
        return HistoryImageDecision(
            action=HistoryImageAction.NONE,
            reason="no_trigger_signal",
            confidence=confidence
        )
    
    # 根据 mode 和候选情况决定动作
    num_candidates = len(candidate_images)
    
    # 连续表情包拼图判定
    if (enable_collage and 
        mode in ("hybrid", "inline") and 
        has_comparison and 
        num_candidates >= 2 and 
        num_candidates <= collage_max):
        # 检查是否是连续发送（时间窗口内，这里简化为存在多张候选就算）
        return HistoryImageDecision(
            action=HistoryImageAction.COLLAGE,
            images_to_inject=candidate_images[:collage_max],
            reason=f"collage_triggered:comparison+{num_candidates}_images",
            confidence=confidence
        )
    
    # inline 模式或 hybrid 高置信
    if mode in ("inline", "hybrid") and confidence >= 0.6:
        images_to_inject = candidate_images[:inline_max]
        return HistoryImageDecision(
            action=HistoryImageAction.INLINE,
            images_to_inject=images_to_inject,
            reason=f"inline:confidence={confidence:.2f}",
            confidence=confidence
        )
    
    # two-stage 模式或 hybrid 中等置信
    if mode in ("two_stage", "hybrid") and confidence >= 0.3:
        # 收集候选 msg_ids
        msg_ids = list({img.message_id for img in candidate_images[:two_stage_max + 2]})
        return HistoryImageDecision(
            action=HistoryImageAction.TWO_STAGE,
            candidate_msg_ids=msg_ids,
            reason=f"two_stage:confidence={confidence:.2f}",
            confidence=confidence
        )
    
    return HistoryImageDecision(
        action=HistoryImageAction.NONE,
        reason="fallback_none",
        confidence=confidence
    )


def build_image_mapping_hint(images: List[CachedImage]) -> str:
    """构建图片 -> msg_id 映射提示
    
    Args:
        images: 图片列表
        
    Returns:
        格式化的映射提示字符串
    """
    if not images:
        return ""
    
    mapping_parts = []
    for i, img in enumerate(images):
        mapping_parts.append(f"Image {i+1} -> <msg_id:{img.message_id}>")
    
    mapping_str = ", ".join(mapping_parts)
    return f"[System Note: Attached history images mapping: {mapping_str}]"


def build_candidate_hint(msg_ids: List[str]) -> str:
    """构建两阶段候选 msg_id 提示
    
    Args:
        msg_ids: 候选 msg_id 列表
        
    Returns:
        格式化的候选提示字符串
    """
    if not msg_ids:
        return ""
    
    ids_str = ", ".join(f"<msg_id:{mid}>" for mid in msg_ids)
    return (
        f"[System Note: History images available for retrieval: {ids_str}. "
        f"Use fetch_history_images tool if you need to see specific images.]"
    )
