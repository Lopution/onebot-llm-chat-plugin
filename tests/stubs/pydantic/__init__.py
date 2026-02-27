"""tests 专用 pydantic v2 轻量 stub（仅在缺少真实 pydantic 依赖时由 conftest 注入）。

覆盖本仓库测试所需的最小功能：
- `BaseModel`
- `field_validator()` / `model_validator()` decorator（收集并执行）
- `ValidationError`

注意：这不是完整 pydantic，实现仅服务于本仓库 tests。
"""

from __future__ import annotations

import copy
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple


class ValidationError(Exception):
    """非常精简的 ValidationError：仅保证可被 `pytest.raises()` 捕获与字符串化。"""

    def __init__(self, messages: List[str]):
        self.messages = messages
        super().__init__("\n".join(messages))


def _mark_validator(obj: Any, *, kind: str, fields: Tuple[str, ...] | None = None, mode: str | None = None) -> Any:
    # 兼容 `@classmethod` / `@staticmethod` 包裹（本仓库字段校验器使用 @classmethod）
    wrapper: Optional[type] = None
    fn = obj

    if isinstance(obj, classmethod):
        wrapper = classmethod
        fn = obj.__func__
    elif isinstance(obj, staticmethod):
        wrapper = staticmethod
        fn = obj.__func__

    setattr(fn, "__pydantic_stub_validator_kind__", kind)
    if fields is not None:
        setattr(fn, "__pydantic_stub_validator_fields__", fields)
    if mode is not None:
        setattr(fn, "__pydantic_stub_validator_mode__", mode)

    if wrapper is not None:
        return wrapper(fn)
    return fn


def field_validator(*fields: str, **_kwargs: Any) -> Callable[[Any], Any]:
    def deco(obj: Any) -> Any:
        return _mark_validator(obj, kind="field", fields=tuple(fields))

    return deco


def model_validator(*_args: Any, mode: str = "after", **_kwargs: Any) -> Callable[[Any], Any]:
    def deco(obj: Any) -> Any:
        return _mark_validator(obj, kind="model", mode=mode)

    return deco


# ==================== Pydantic v2 常用组件 ====================

def Field(*args: Any, **kwargs: Any) -> Any:
    """pydantic.Field 占位实现，返回默认值或 None"""
    if args:
        return args[0]  # 第一个位置参数作为默认值
    return kwargs.get("default", None)


def ConfigDict(**kwargs: Any) -> Dict[str, Any]:
    """pydantic.ConfigDict 占位实现，返回配置字典"""
    return kwargs


def PrivateAttr(default: Any = None, **kwargs: Any) -> Any:
    """pydantic.PrivateAttr 占位实现"""
    return default


def computed_field(*args: Any, **kwargs: Any) -> Callable[[Any], Any]:
    """pydantic.computed_field 装饰器占位"""
    def deco(fn: Any) -> Any:
        return property(fn) if not isinstance(fn, property) else fn
    if args and callable(args[0]):
        return deco(args[0])
    return deco


class SecretStr(str):
    """pydantic.SecretStr 占位实现"""
    def get_secret_value(self) -> str:
        return str(self)


class HttpUrl(str):
    """pydantic.HttpUrl 占位实现"""
    pass


class AnyUrl(str):
    """pydantic.AnyUrl 占位实现"""
    pass


class BaseModel:
    """极简 BaseModel：按注解字段赋值并执行收集到的 validators。"""

    __field_validators__: ClassVar[Dict[str, List[str]]]
    __model_validators_after__: ClassVar[List[str]]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        cls.__field_validators__ = {}
        cls.__model_validators_after__ = []

        for name, attr in cls.__dict__.items():
            fn = None
            if isinstance(attr, classmethod):
                fn = attr.__func__
            elif isinstance(attr, staticmethod):
                fn = attr.__func__
            elif callable(attr):
                fn = attr

            if fn is None:
                continue

            kind = getattr(fn, "__pydantic_stub_validator_kind__", None)
            if kind == "field":
                fields = getattr(fn, "__pydantic_stub_validator_fields__", ())
                for f in fields:
                    cls.__field_validators__.setdefault(f, []).append(name)
            elif kind == "model" and getattr(fn, "__pydantic_stub_validator_mode__", None) == "after":
                cls.__model_validators_after__.append(name)

    def __init__(self, **data: Any) -> None:
        errors: List[str] = []
        annotations = getattr(self.__class__, "__annotations__", {})

        # 1) 设置字段（默认值 + 入参）
        for field in annotations.keys():
            if field in data:
                value = data[field]
            else:
                if hasattr(self.__class__, field):
                    value = copy.deepcopy(getattr(self.__class__, field))
                else:
                    value = None

            # 2) 字段级 validators（按声明顺序执行）
            for validator_name in self.__class__.__field_validators__.get(field, []):
                try:
                    validator = getattr(self.__class__, validator_name)
                    # validator 可能是 classmethod（已绑定 cls）或普通 callable
                    value = validator(value)
                except Exception as e:  # noqa: BLE001 - 测试 stub：收集并统一抛出
                    errors.append(str(e))

            setattr(self, field, value)

        # 记录显式传入的字段集合（pydantic v2: model_fields_set）
        # 用于仓库内配置治理/别名注入逻辑：不能覆盖用户显式设置。
        try:
            self.model_fields_set = {k for k in data.keys() if k in annotations}
        except Exception:
            self.model_fields_set = set()

        # 允许额外字段（pydantic 默认 forbids/ignores 取决于配置；这里简化为接受）
        for k, v in data.items():
            if k not in annotations:
                setattr(self, k, v)

        # 3) model_validator(after)
        if not errors:
            for validator_name in self.__class__.__model_validators_after__:
                try:
                    validator = getattr(self, validator_name)
                    validator()
                except Exception as e:  # noqa: BLE001
                    errors.append(str(e))

        if errors:
            raise ValidationError(errors)
