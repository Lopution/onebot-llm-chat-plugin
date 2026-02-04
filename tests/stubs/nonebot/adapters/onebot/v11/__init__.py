"""tests 专用 nonebot.adapters.onebot.v11 stub。

用于让插件模块在无 nonebot-adapter-onebot 依赖时仍可 import。
仅提供类型占位与极简消息段实现，满足本仓库测试用例。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


class Adapter:
    """仅用于 bot 入口代码的类型占位。"""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class Bot:
    self_id: str = "0"

    async def send(self, *_args: Any, **_kwargs: Any) -> Any:
        return None

    async def call_api(self, *_args: Any, **_kwargs: Any) -> Any:
        return {}

    async def send_private_msg(self, *_args: Any, **_kwargs: Any) -> Any:
        return None

    async def get_group_member_info(self, *_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {}

    async def get_msg(self, *_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {}


class _BaseEvent:
    def get_plaintext(self) -> str:
        return ""


class PrivateMessageEvent(_BaseEvent):
    user_id: int = 0
    message_id: int = 0
    original_message: Any = []
    message: Any = []


class GroupMessageEvent(_BaseEvent):
    group_id: int = 0
    user_id: int = 0
    self_id: str = "0"
    message_id: int = 0
    to_me: bool = False
    original_message: Any = []
    message: Any = []
    sender: Any = None


class Message(list):
    """消息类，继承自 list。"""
    
    def __init__(self, message: Any = None) -> None:
        super().__init__()
        if message is not None:
            if isinstance(message, str):
                self.append(MessageSegment.text(message))
            elif isinstance(message, MessageSegment):
                self.append(message)
            elif isinstance(message, list):
                self.extend(message)
    
    def __add__(self, other: Any) -> "Message":
        """消息拼接"""
        result = Message(list(self))
        if isinstance(other, str):
            result.append(MessageSegment.text(other))
        elif isinstance(other, MessageSegment):
            result.append(other)
        elif isinstance(other, list):
            result.extend(other)
        return result
    
    def __radd__(self, other: Any) -> "Message":
        """反向消息拼接"""
        result = Message()
        if isinstance(other, str):
            result.append(MessageSegment.text(other))
        elif isinstance(other, MessageSegment):
            result.append(other)
        elif isinstance(other, list):
            result.extend(other)
        result.extend(self)
        return result


@dataclass
class MessageSegment:
    type: str
    data: Dict[str, Any]

    def __add__(self, other: Any) -> Message:
        """消息段拼接，返回 Message 类型"""
        result = Message()
        result.append(self)
        if isinstance(other, str):
            result.append(MessageSegment.text(other))
        elif isinstance(other, MessageSegment):
            result.append(other)
        elif isinstance(other, Message):
            result.extend(other)
        return result

    def __radd__(self, other: Any) -> Message:
        """反向消息段拼接，返回 Message 类型"""
        result = Message()
        if isinstance(other, str):
            result.append(MessageSegment.text(other))
        elif isinstance(other, MessageSegment):
            result.append(other)
        elif isinstance(other, Message):
            result.extend(other)
        result.append(self)
        return result

    @staticmethod
    def reply(message_id: int) -> "MessageSegment":
        """回复消息段"""
        return MessageSegment(type="reply", data={"id": str(message_id)})

    @staticmethod
    def text(text: str) -> "MessageSegment":
        """文本消息段"""
        return MessageSegment(type="text", data={"text": text})

    @staticmethod
    def image(file: str, **kwargs: Any) -> "MessageSegment":
        """图片消息段"""
        data = {"file": file}
        data.update(kwargs)
        return MessageSegment(type="image", data=data)

    @staticmethod
    def at(user_id: int | str) -> "MessageSegment":
        """@某人消息段"""
        return MessageSegment(type="at", data={"qq": str(user_id)})

    @staticmethod
    def face(id_: int) -> "MessageSegment":
        """表情消息段"""
        return MessageSegment(type="face", data={"id": str(id_)})

    @staticmethod
    def record(file: str, **kwargs: Any) -> "MessageSegment":
        """语音消息段"""
        data = {"file": file}
        data.update(kwargs)
        return MessageSegment(type="record", data=data)

    @staticmethod
    def video(file: str, **kwargs: Any) -> "MessageSegment":
        """视频消息段"""
        data = {"file": file}
        data.update(kwargs)
        return MessageSegment(type="video", data=data)

    @staticmethod
    def share(url: str, title: str, **kwargs: Any) -> "MessageSegment":
        """链接分享消息段"""
        data = {"url": url, "title": title}
        data.update(kwargs)
        return MessageSegment(type="share", data=data)

    @staticmethod
    def json(data: str) -> "MessageSegment":
        """JSON 消息段"""
        return MessageSegment(type="json", data={"data": data})

    @staticmethod
    def xml(data: str) -> "MessageSegment":
        """XML 消息段"""
        return MessageSegment(type="xml", data={"data": data})

