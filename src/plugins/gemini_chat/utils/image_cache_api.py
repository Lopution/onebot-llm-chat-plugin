from __future__ import annotations

from typing import Optional

from .image_cache_core import ImageCache


_image_cache: Optional[ImageCache] = None


def get_image_cache() -> ImageCache:
    """获取图片缓存单例"""
    global _image_cache
    if _image_cache is None:
        _image_cache = ImageCache()
    return _image_cache


def init_image_cache(
    max_gap: int = 10,
    require_keyword: bool = True,
    max_images: int = 10,
    max_entries: int = 200,
    keywords: list[str] | None = None,
) -> ImageCache:
    """初始化图片缓存"""
    global _image_cache
    _image_cache = ImageCache(
        max_gap=max_gap,
        require_keyword=require_keyword,
        max_images=max_images,
        max_entries=max_entries,
        keywords=keywords,
    )
    return _image_cache
