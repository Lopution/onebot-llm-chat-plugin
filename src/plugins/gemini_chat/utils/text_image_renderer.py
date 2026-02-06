"""长文本渲染图片工具。

用于在 OneBot 不支持 Forward/Quote 或发送失败时，将文本渲染为图片后发送。
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, List

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]

_PADDING_X = 36
_PADDING_Y = 28
_LINE_SPACING = 10
_MAX_IMAGE_WIDTH = 2000
_MIN_IMAGE_WIDTH = 320
_MAX_FONT_SIZE = 72
_MIN_FONT_SIZE = 12
_MAX_TEXT_CHARS = 200000
_MIN_TEXT_CHARS = 200

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
)


def _clamp_int(value: int, lower: int, upper: int) -> int:
    return max(lower, min(int(value), upper))


def _load_font(font_size: int) -> Any:
    if ImageFont is None:
        raise RuntimeError("Pillow 未安装，无法渲染文本图片")
    for font_path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(font_path, font_size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_width(draw: Any, text: str, font: Any) -> float:
    if not text:
        return 0.0
    try:
        return float(draw.textlength(text, font=font))
    except Exception:
        bbox = draw.textbbox((0, 0), text, font=font)
        if not bbox:
            return 0.0
        return float(max(0, bbox[2] - bbox[0]))


def _line_height(draw: Any, font: Any) -> int:
    bbox = draw.textbbox((0, 0), "中A", font=font)
    if not bbox:
        return 20
    return max(16, int(bbox[3] - bbox[1]))


def _wrap_line(
    draw: Any,
    line: str,
    font: Any,
    max_width: int,
) -> List[str]:
    if not line:
        return [""]

    wrapped: List[str] = []
    current = ""
    for ch in line:
        candidate = f"{current}{ch}"
        if current and _text_width(draw, candidate, font) > max_width:
            wrapped.append(current)
            current = ch
        else:
            current = candidate

    if current:
        wrapped.append(current)

    return wrapped or [""]


def _normalize_text(text: str, max_chars: int) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        normalized = "(空内容)"
    if len(normalized) > max_chars:
        normalized = f"{normalized[:max_chars]}\n\n[内容过长，已截断]"
    return normalized


def render_text_to_png_bytes(
    text: str,
    max_width: int = 960,
    font_size: int = 24,
    max_chars: int = 12000,
) -> bytes:
    """将文本渲染为 PNG 字节流。"""
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow 未安装，无法渲染文本图片")
    width = _clamp_int(max_width, _MIN_IMAGE_WIDTH, _MAX_IMAGE_WIDTH)
    size = _clamp_int(font_size, _MIN_FONT_SIZE, _MAX_FONT_SIZE)
    chars = _clamp_int(max_chars, _MIN_TEXT_CHARS, _MAX_TEXT_CHARS)
    content = _normalize_text(text, chars)

    font = _load_font(size)
    probe = Image.new("RGB", (width, 10), "white")
    probe_draw = ImageDraw.Draw(probe)
    text_max_width = max(1, width - _PADDING_X * 2)

    lines: List[str] = []
    for raw in content.split("\n"):
        lines.extend(_wrap_line(probe_draw, raw, font, text_max_width))
    if not lines:
        lines = ["(空内容)"]

    line_height = _line_height(probe_draw, font)
    content_height = len(lines) * line_height + max(0, len(lines) - 1) * _LINE_SPACING
    image_height = _PADDING_Y * 2 + max(content_height, line_height)

    image = Image.new("RGB", (width, image_height), "white")
    draw = ImageDraw.Draw(image)

    y = _PADDING_Y
    for line in lines:
        draw.text((_PADDING_X, y), line, font=font, fill=(24, 24, 24))
        y += line_height + _LINE_SPACING

    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
