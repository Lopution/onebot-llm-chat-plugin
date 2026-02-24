"""Host-agnostic contracts for adapters and core engine.

The goal of this module is to provide JSON-serializable structures that can be
shared by host adapters and remote core-service adapters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional


ContentPartKind = Literal["text", "mention", "reply", "image", "attachment"]
Role = Literal["user", "assistant", "system", "tool"]


@dataclass
class ContentPart:
    """A unified semantic content part.

    - `kind=text`: use `text`
    - `kind=mention`: use `target_id` and optional `text`
    - `kind=reply`: use `target_id` and optional `text`
    - `kind=image`: use `asset_ref` and optional `text`
    - `kind=attachment`: use `asset_ref` and optional `text`
    """

    kind: ContentPartKind
    text: str = ""
    target_id: str = ""
    asset_ref: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        valid_kinds = {"text", "mention", "reply", "image", "attachment"}
        if self.kind not in valid_kinds:
            raise ValueError(f"unsupported content part kind: {self.kind}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContentPart":
        return cls(
            kind=str(data.get("kind", "text")),
            text=str(data.get("text", "")),
            target_id=str(data.get("target_id", "")),
            asset_ref=str(data.get("asset_ref", "")),
            meta=dict(data.get("meta", {}) or {}),
        )


@dataclass
class Author:
    id: str
    nickname: str = ""
    role: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Author":
        return cls(
            id=str(data.get("id", "")),
            nickname=str(data.get("nickname", "")),
            role=str(data.get("role", "")),
            meta=dict(data.get("meta", {}) or {}),
        )


@dataclass
class EventEnvelope:
    """Host-independent inbound event envelope."""

    schema_version: int
    session_id: str
    platform: str
    protocol: str
    message_id: str
    timestamp: float
    author: Author
    bot_self_id: str = ""
    content_parts: List[ContentPart] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "platform": self.platform,
            "protocol": self.protocol,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "author": self.author.to_dict(),
            "bot_self_id": self.bot_self_id,
            "content_parts": [part.to_dict() for part in self.content_parts],
            "meta": dict(self.meta),
            "raw": dict(self.raw),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventEnvelope":
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            session_id=str(data.get("session_id", "")),
            platform=str(data.get("platform", "")),
            protocol=str(data.get("protocol", "")),
            message_id=str(data.get("message_id", "")),
            timestamp=float(data.get("timestamp", 0.0)),
            author=Author.from_dict(dict(data.get("author", {}) or {})),
            bot_self_id=str(data.get("bot_self_id", "")),
            content_parts=[ContentPart.from_dict(dict(p or {})) for p in list(data.get("content_parts", []) or [])],
            meta=dict(data.get("meta", {}) or {}),
            raw=dict(data.get("raw", {}) or {}),
        )


@dataclass
class ChatMessage:
    """Legacy chat message format (kept for backward compatibility)."""

    role: Role
    text: str
    user_id: str = ""
    group_id: str = ""
    message_id: str = ""
    mentions: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatMessage":
        return cls(
            role=str(data.get("role", "user")),  # type: ignore[arg-type]
            text=str(data.get("text", "")),
            user_id=str(data.get("user_id", "")),
            group_id=str(data.get("group_id", "")),
            message_id=str(data.get("message_id", "")),
            mentions=[str(x) for x in list(data.get("mentions", []) or [])],
            images=[str(x) for x in list(data.get("images", []) or [])],
            raw=dict(data.get("raw", {}) or {}),
        )


@dataclass
class ChatSession:
    """Legacy chat session format (kept for backward compatibility)."""

    user_id: str
    group_id: Optional[str] = None
    is_private: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatSession":
        group_id = data.get("group_id")
        return cls(
            user_id=str(data.get("user_id", "")),
            group_id=str(group_id) if group_id is not None else None,
            is_private=bool(data.get("is_private", False)),
        )


ActionType = Literal["send_message", "noop"]


@dataclass
class SendMessageAction:
    type: ActionType
    session_id: str
    parts: List[ContentPart] = field(default_factory=list)
    reply_to: str = ""
    mentions: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type != "send_message":
            raise ValueError(f"invalid action type for SendMessageAction: {self.type}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "session_id": self.session_id,
            "parts": [part.to_dict() for part in self.parts],
            "reply_to": self.reply_to,
            "mentions": list(self.mentions),
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SendMessageAction":
        return cls(
            type=str(data.get("type", "send_message")),  # type: ignore[arg-type]
            session_id=str(data.get("session_id", "")),
            parts=[ContentPart.from_dict(dict(p or {})) for p in list(data.get("parts", []) or [])],
            reply_to=str(data.get("reply_to", "")),
            mentions=[str(x) for x in list(data.get("mentions", []) or [])],
            meta=dict(data.get("meta", {}) or {}),
        )


@dataclass
class NoopAction:
    type: ActionType
    reason: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type != "noop":
            raise ValueError(f"invalid action type for NoopAction: {self.type}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NoopAction":
        return cls(
            type=str(data.get("type", "noop")),  # type: ignore[arg-type]
            reason=str(data.get("reason", "")),
            meta=dict(data.get("meta", {}) or {}),
        )


@dataclass
class PlatformCapabilities:
    """Adapter capability declaration.

    Core can use this declaration for capability-based fallback instead of
    platform-specific branching.
    """

    supports_reply: bool = True
    supports_image_send: bool = True
    supports_image_receive: bool = True
    supports_mentions: bool = True
    supports_forward_message: bool = False
    supports_history_fetch: bool = False
    supports_member_info: bool = False
    supports_file_resolve: bool = False
    supports_message_fetch: bool = False
    max_text_length: int = 0
    platform_name: str = ""


@dataclass(frozen=True)
class SessionKey:
    """Unified cross-platform session identity.

    Canonical format: ``platform:scope:conversation_id:user_id``.

    Examples:
      - ``qq:group:123456:789012``
      - ``telegram:private::user123``
      - ``discord:guild:server#channel:user456``
    """

    platform: str
    scope: str
    conversation_id: str
    user_id: str

    def __str__(self) -> str:
        return f"{self.platform}:{self.scope}:{self.conversation_id}:{self.user_id}"

    @classmethod
    def parse(cls, key: str) -> "SessionKey":
        parts = str(key).split(":", 3)
        if len(parts) == 4:
            return cls(
                platform=parts[0],
                scope=parts[1],
                conversation_id=parts[2],
                user_id=parts[3],
            )
        if len(parts) == 3:
            return cls(
                platform=parts[0],
                scope=parts[1],
                conversation_id=parts[2],
                user_id="",
            )
        if len(parts) == 2:
            return cls(
                platform="",
                scope=parts[0],
                conversation_id=parts[1],
                user_id="",
            )
        raise ValueError(f"invalid session key: {key}")

    @property
    def is_group(self) -> bool:
        return self.scope in ("group", "guild", "channel")

    @property
    def conversation_key(self) -> str:
        return f"{self.platform}:{self.scope}:{self.conversation_id}"
