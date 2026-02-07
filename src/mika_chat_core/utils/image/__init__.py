# 图片处理统一模块
"""
整合图片处理相关功能：
- processor.py: 图片下载、Base64编码、磁盘缓存
- cache.py: 跨消息图片引用、消息间隔跟踪
"""

# 从 processor 导出（原 image_processor.py）
from .processor import (
    ImageProcessor,
    ImageProcessError,
    get_image_processor,
    extract_images,
    CACHE_DIR,
    SUPPORTED_FORMATS,
)

# 从 cache 导出（原 recent_images.py）
from .cache import (
    ImageCache,
    CachedImage,
    CacheEntry,
    get_image_cache,
)

__all__ = [
    # Processor
    "ImageProcessor",
    "ImageProcessError", 
    "get_image_processor",
    "extract_images",
    "CACHE_DIR",
    "SUPPORTED_FORMATS",
    # Cache
    "ImageCache",
    "CachedImage",
    "CacheEntry",
    "get_image_cache",
]
