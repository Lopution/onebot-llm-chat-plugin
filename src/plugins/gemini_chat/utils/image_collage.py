# 图片拼图模块
"""
将多张图片合成为一张拼图，用于减少图片数量限制。

功能:
- 支持 2-4 张图片横向/网格拼接
- 可配置目标尺寸上限
- 失败时返回 None，调用方可回退到普通逻辑

依赖:
- Pillow (PIL) - 可选依赖，未安装时功能降级
"""

from __future__ import annotations

import base64
import io
from typing import List, Optional, Tuple

from nonebot import logger as log

# 尝试导入 Pillow
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    log.warning("Pillow 未安装，拼图功能不可用。安装方式: pip install Pillow")


def is_collage_available() -> bool:
    """检查拼图功能是否可用"""
    return HAS_PIL


def _resize_to_fit(img: "Image.Image", max_size: int) -> "Image.Image":
    """等比缩放图片使其最长边不超过 max_size"""
    w, h = img.size
    if max(w, h) <= max_size:
        return img
    
    if w > h:
        new_w = max_size
        new_h = int(h * max_size / w)
    else:
        new_h = max_size
        new_w = int(w * max_size / h)
    
    return img.resize((new_w, new_h), Image.Resampling.LANCZOS)


def _calculate_layout(num_images: int) -> Tuple[int, int]:
    """计算拼图布局 (cols, rows)"""
    if num_images <= 2:
        return (num_images, 1)  # 横排
    elif num_images <= 4:
        return (2, 2)  # 2x2 网格
    else:
        # 超过4张，取前4张
        return (2, 2)


def create_collage(
    image_data_list: List[bytes],
    target_max_px: int = 768,
    background_color: Tuple[int, int, int] = (255, 255, 255),
    padding: int = 4,
) -> Optional[Tuple[str, str]]:
    """创建拼图
    
    Args:
        image_data_list: 图片二进制数据列表
        target_max_px: 拼图最大边长（px）
        background_color: 背景色 RGB
        padding: 图片间隔（px）
        
    Returns:
        (base64_data, mime_type) 或 None（失败时）
    """
    if not HAS_PIL:
        log.warning("Pillow 未安装，无法创建拼图")
        return None
    
    if not image_data_list:
        return None
    
    if len(image_data_list) == 1:
        # 只有一张图，直接返回（不需要拼接）
        try:
            img = Image.open(io.BytesIO(image_data_list[0]))
            img = _resize_to_fit(img, target_max_px)
            
            output = io.BytesIO()
            # 统一转为 RGB 避免 RGBA 问题
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, background_color)
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            
            img.save(output, format="JPEG", quality=85)
            base64_data = base64.b64encode(output.getvalue()).decode("utf-8")
            return base64_data, "image/jpeg"
        except Exception as e:
            log.warning(f"处理单张图片失败: {e}")
            return None
    
    try:
        # 加载所有图片
        images: List[Image.Image] = []
        for data in image_data_list[:4]:  # 最多4张
            try:
                img = Image.open(io.BytesIO(data))
                images.append(img)
            except Exception as e:
                log.warning(f"加载图片失败: {e}")
                continue
        
        if not images:
            return None
        
        # 计算每张图片在拼图中的目标尺寸
        cols, rows = _calculate_layout(len(images))
        
        # 每个格子的大小
        cell_size = (target_max_px - padding * (cols + 1)) // cols
        
        # 缩放所有图片到格子大小
        resized_images = []
        for img in images:
            # 等比缩放到格子内
            w, h = img.size
            scale = min(cell_size / w, cell_size / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            resized_images.append(resized)
        
        # 创建画布
        canvas_w = cols * cell_size + (cols + 1) * padding
        canvas_h = rows * cell_size + (rows + 1) * padding
        canvas = Image.new("RGB", (canvas_w, canvas_h), background_color)
        
        # 放置图片
        for i, img in enumerate(resized_images):
            col = i % cols
            row = i // cols
            
            # 计算居中位置
            x = padding + col * (cell_size + padding) + (cell_size - img.width) // 2
            y = padding + row * (cell_size + padding) + (cell_size - img.height) // 2
            
            # 处理透明通道
            if img.mode == "RGBA":
                # 创建纯色背景
                bg = Image.new("RGB", img.size, background_color)
                bg.paste(img, mask=img.split()[3])
                canvas.paste(bg, (x, y))
            else:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                canvas.paste(img, (x, y))
        
        # 添加序号标签（可选，帮助模型区分）
        # 暂时不加，保持简洁
        
        # 输出为 JPEG
        output = io.BytesIO()
        canvas.save(output, format="JPEG", quality=85)
        base64_data = base64.b64encode(output.getvalue()).decode("utf-8")
        
        log.info(f"拼图创建成功 | images={len(resized_images)} | size={canvas_w}x{canvas_h}")
        
        return base64_data, "image/jpeg"
        
    except Exception as e:
        log.error(f"创建拼图失败: {e}", exc_info=True)
        return None


async def create_collage_from_urls(
    image_urls: List[str],
    target_max_px: int = 768,
) -> Optional[Tuple[str, str]]:
    """从 URL 列表创建拼图（异步下载）
    
    Args:
        image_urls: 图片 URL 列表
        target_max_px: 拼图最大边长
        
    Returns:
        (base64_data, mime_type) 或 None
    """
    if not HAS_PIL:
        return None
    
    if not image_urls:
        return None
    
    # 导入图片处理器进行下载
    try:
        from .image_processor import get_image_processor
        processor = get_image_processor()
        
        image_data_list: List[bytes] = []
        
        for url in image_urls[:4]:
            try:
                # 使用现有的下载和缓存机制
                base64_data, _ = await processor.download_and_encode(url)
                # 解码回 bytes
                image_bytes = base64.b64decode(base64_data)
                image_data_list.append(image_bytes)
            except Exception as e:
                log.warning(f"下载图片用于拼图失败: {e}")
                continue
        
        if not image_data_list:
            return None
        
        return create_collage(image_data_list, target_max_px)
        
    except ImportError:
        log.warning("无法导入 image_processor，拼图功能不可用")
        return None
