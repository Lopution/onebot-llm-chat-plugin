"""事件上下文抽象模块（OneBot v11/v12 兼容）。

将 handler/tool 需要的关键字段抽象为统一结构，避免直接依赖特定适配器的事件类型。

功能：
- OneBot v11（id 常为 int）/ v12（id 常为 str）统一处理
- 未来接入更多平台时，业务逻辑只需要补"适配层"

会话 Key 规则（兼容已有 SQLite 历史数据）：
- 群聊：group:{group_id}
- 私聊：private:{user_id}

相关模块：
- [`handlers`](../handlers.py:1): 消息处理，使用本模块提取上下文
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ..contracts import EventEnvelope


@dataclass(frozen=True)
class EventContext:
    """从事件中抽取出来的“通用上下文”。

    字段说明：
    - platform: 平台/适配器标识（来自 bot.type）
    - user_id/group_id/message_id: 统一转为 str（v11/v12 类型不同）
    - session_key: 与 SQLiteContextStore 的 key 规则对齐（用于锁与存储）
    - sender_name: 尽量取群名片/昵称，失败则回退 user_id
    """

    platform: str
    user_id: str
    group_id: Optional[str]
    message_id: Optional[str]
    is_group: bool
    is_tome: bool
    plaintext: str
    session_key: str
    sender_name: str


def _normalize_platform(raw: Any) -> str:
    platform = str(raw or "").strip().lower().replace(" ", "_")
    return platform or "unknown"


def _get_session_id(event: Any) -> str:
    getter = getattr(event, "get_session_id", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            return ""
    return ""


def _parse_group_id_from_session_id(session_id: str) -> Optional[str]:
    # 常见 OneBot session_id 格式：
    # - 群聊：group_{group_id}_{user_id}
    # - 私聊：{user_id} 或 private_{user_id}（不同实现略有差异）
    sid = (session_id or "").strip()
    if not sid.startswith("group_"):
        return None
    parts = sid.split("_")
    if len(parts) >= 3 and parts[1]:
        return parts[1]
    return None


def _get_user_id(event: Any) -> str:
    if hasattr(event, "user_id"):
        try:
            return str(getattr(event, "user_id"))
        except Exception:
            pass

    getter = getattr(event, "get_user_id", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            pass

    session_id = _get_session_id(event)
    # 群聊常见格式：group_{group_id}_{user_id}
    if session_id.startswith("group_"):
        parts = session_id.split("_")
        if len(parts) >= 3:
            return parts[2]

    return ""


def _get_group_id(event: Any) -> Optional[str]:
    if hasattr(event, "group_id"):
        try:
            gid = getattr(event, "group_id")
            if gid is None:
                return None
            gid_str = str(gid).strip()
            return gid_str or None
        except Exception:
            return None

    session_id = _get_session_id(event)
    return _parse_group_id_from_session_id(session_id)


def _get_message_id(event: Any) -> Optional[str]:
    if hasattr(event, "message_id"):
        try:
            mid = getattr(event, "message_id")
            if mid is None:
                return None
            mid_str = str(mid).strip()
            return mid_str or None
        except Exception:
            return None

    getter = getattr(event, "get_message_id", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            return None

    return None


def _is_tome(event: Any) -> bool:
    if hasattr(event, "to_me"):
        try:
            return bool(getattr(event, "to_me"))
        except Exception:
            pass

    getter = getattr(event, "is_tome", None)
    if callable(getter):
        try:
            return bool(getter())
        except Exception:
            return False

    return False


def _get_plaintext(event: Any) -> str:
    getter = getattr(event, "get_plaintext", None)
    if callable(getter):
        try:
            return str(getter() or "")
        except Exception:
            return ""
    return ""


def _get_sender_name(event: Any, user_id: str) -> str:
    sender = getattr(event, "sender", None)
    if sender is None:
        return user_id

    try:
        if isinstance(sender, dict):
            card = str(sender.get("card") or "").strip()
            nick = str(sender.get("nickname") or "").strip()
            return card or nick or user_id
        card = str(getattr(sender, "card", "") or "").strip()
        nick = str(getattr(sender, "nickname", "") or "").strip()
        return card or nick or user_id
    except Exception:
        return user_id


def _build_event_context_with_platform(platform: str, event: Any) -> EventContext:
    """在已知 platform 标识的前提下构建 EventContext。"""
    user_id = _get_user_id(event)
    group_id = _get_group_id(event)
    message_id = _get_message_id(event)
    is_group = group_id is not None
    is_tome = _is_tome(event)
    plaintext = _get_plaintext(event)
    session_key = f"group:{group_id}" if group_id else f"private:{user_id}"
    sender_name = _get_sender_name(event, user_id)

    return EventContext(
        platform=platform,
        user_id=user_id,
        group_id=group_id,
        message_id=message_id,
        is_group=is_group,
        is_tome=is_tome,
        plaintext=plaintext,
        session_key=session_key,
        sender_name=sender_name,
    )


def build_event_context(bot: Any, event: Any) -> EventContext:
    """从 bot/event 中抽取 EventContext（best-effort，不抛异常）。"""
    platform = _normalize_platform(getattr(bot, "type", None))
    return _build_event_context_with_platform(platform, event)


def build_event_context_from_event(event: Any, platform: str = "unknown") -> EventContext:
    """仅从 event 构建 EventContext。

    适用于 matcher rule 场景（函数签名只有 event，拿不到 bot）。
    """
    return _build_event_context_with_platform(_normalize_platform(platform), event)


def build_event_context_from_envelope(envelope: EventEnvelope) -> EventContext:
    """仅从 EventEnvelope 构建 EventContext（不依赖宿主对象）。"""
    meta = envelope.meta or {}
    user_id = str(envelope.author.id or meta.get("user_id", "") or "").strip()
    group_id_raw = str(meta.get("group_id", "") or "").strip()
    group_id = group_id_raw or None
    is_group = bool(group_id)

    plaintext = " ".join(
        part.text.strip()
        for part in envelope.content_parts
        if part.kind == "text" and str(part.text or "").strip()
    ).strip()

    session_key = str(envelope.session_id or "").strip()
    if not session_key:
        session_key = f"group:{group_id}" if group_id else f"private:{user_id}"

    return EventContext(
        platform=_normalize_platform(envelope.platform),
        user_id=user_id,
        group_id=group_id,
        message_id=str(envelope.message_id or "").strip() or None,
        is_group=is_group,
        is_tome=bool(meta.get("is_tome", False)),
        plaintext=plaintext,
        session_key=session_key,
        sender_name=str(envelope.author.nickname or user_id or "").strip(),
    )
