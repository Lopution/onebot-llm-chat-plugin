"""图片处理模块。

提供图片的下载、格式转换、缓存等功能，支持：
- 异步并发下载（支持 QQ 图片服务器等多种来源）
- 自动格式转换（WebP/GIF -> JPEG/PNG）
- 本地磁盘缓存（LRU 淘汰策略）
- SSRF 防护（内网 IP 校验）

环境变量：
- GEMINI_IMAGE_CACHE_DIR: 图片缓存目录
- GEMINI_DATA_DIR: 数据根目录（缓存位于 <dir>/gemini_chat/image_cache）
（可选）nonebot-plugin-localstore：若未配置上述环境变量，则优先使用 localstore 的 cache 目录（跨平台可写）

相关模块：
- [`image_cache_core`](image_cache_core.py:1): 跨消息图片缓存
- [`image_collage`](image_collage.py:1): 多图拼接
"""

import asyncio
import base64
import hashlib
import os
import time
import ipaddress
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from urllib.parse import quote, urlparse

import httpx

from nonebot import logger as log


def _get_default_cache_dir() -> Path:
    """获取图片缓存目录默认路径（优先环境变量，否则使用 localstore / 项目路径）。"""
    env_path = os.getenv("GEMINI_IMAGE_CACHE_DIR")
    if env_path:
        return Path(env_path)

    # 若未设置专用目录，则优先使用 GEMINI_DATA_DIR
    env_data_dir = os.getenv("GEMINI_DATA_DIR")
    if env_data_dir:
        return Path(env_data_dir) / "gemini_chat" / "image_cache"

    # 未配置环境变量时：优先使用 localstore（跨平台可写、不会依赖 WorkingDirectory）
    try:
        from nonebot_plugin_localstore import get_cache_dir  # type: ignore

        return Path(get_cache_dir("gemini_chat")) / "image_cache"
    except Exception:
        pass
    
    # 使用项目相对路径: bot/data/gemini_chat/image_cache
    project_root = Path(__file__).parent.parent.parent.parent.parent
    return project_root / "data" / "gemini_chat" / "image_cache"


def _is_obviously_local_host(hostname: str) -> bool:
    """对明显本地地址做拒绝（基础 SSRF 防护，默认更安全）。

    注意：这里仅做最小侵入的“明显本地”判定；不解析 DNS，不做完整私网网段判断。
    """

    h = hostname.strip().lower().strip("[]")
    if not h:
        return True
    if h in {"localhost", "localhost.", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(h)
        return ip.is_loopback
    except ValueError:
        return False


def _validate_source_url(url: str) -> None:
    """最小 URL 校验：拒绝非 http/https，拒绝明显本地地址。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ImageProcessError(f"不支持的 URL scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise ImageProcessError("无效的 URL（缺少 hostname）")
    if parsed.hostname and _is_obviously_local_host(parsed.hostname):
        raise ImageProcessError("拒绝访问本地地址（SSRF 防护）")


# ==================== Magic-number constants ====================
# 缓存配置
CACHE_DIR = _get_default_cache_dir()
CACHE_TTL_SECONDS = 3600  # 1 小时
MAX_CACHE_SIZE_MB = 100  # 最大缓存大小 100MB
MAX_IMAGE_SIZE_MB = 10  # 单张图片最大 10MB
MEMORY_CACHE_MAX_ITEMS = 50  # 内存缓存最大条目数

# 支持的图片格式
SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# MIME类型映射
MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


class ImageProcessError(Exception):
    """图片处理错误"""
    pass


class ImageProcessor:
    """图片处理器：负责下载、转换、缓存图片"""
    
    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        cache_ttl: int = CACHE_TTL_SECONDS,
        max_cache_size_mb: int = MAX_CACHE_SIZE_MB,
        max_image_size_mb: int = MAX_IMAGE_SIZE_MB,
        max_concurrency: int = 3,
    ):
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl
        self.max_cache_size_mb = max_cache_size_mb
        self.max_image_size_mb = max_image_size_mb
        self._http_client: Optional[httpx.AsyncClient] = None
        self._download_semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
        # 确保缓存目录存在
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存（URL -> Base64 数据）
        self._memory_cache: Dict[str, Tuple[str, float]] = {}  # {url: (base64_data, timestamp)}
        self._memory_cache_max_items = MEMORY_CACHE_MAX_ITEMS
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )
        return self._http_client
    
    async def close(self):
        """关闭 HTTP 客户端"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
    def _get_url_hash(self, url: str) -> str:
        """获取 URL 的哈希值"""
        return hashlib.md5(url.encode()).hexdigest()
    
    def _get_cache_path(self, url: str) -> Path:
        """获取缓存文件路径"""
        url_hash = self._get_url_hash(url)
        return self.cache_dir / f"{url_hash}.cache"
    
    def _is_cache_valid(self, cache_path: Path) -> bool:
        """检查缓存是否有效"""
        if not cache_path.exists():
            return False
        # 检查是否过期
        mtime = cache_path.stat().st_mtime
        return (time.time() - mtime) < self.cache_ttl
    
    def _get_from_memory_cache(self, url: str) -> Optional[str]:
        """从内存缓存获取"""
        if url in self._memory_cache:
            data, timestamp = self._memory_cache[url]
            if (time.time() - timestamp) < self.cache_ttl:
                log.debug(f"内存缓存命中 | url_hash={self._get_url_hash(url)[:8]}")
                return data
            else:
                del self._memory_cache[url]
        return None
    
    def _set_memory_cache(self, url: str, data: str):
        """设置内存缓存"""
        # 简单的 LRU：如果超出限制，删除最旧的
        if len(self._memory_cache) >= self._memory_cache_max_items:
            oldest_url = min(self._memory_cache.keys(), key=lambda k: self._memory_cache[k][1])
            del self._memory_cache[oldest_url]
        self._memory_cache[url] = (data, time.time())
    
    async def _load_from_disk_cache(self, cache_path: Path) -> Optional[str]:
        """从磁盘缓存加载"""
        try:
            if self._is_cache_valid(cache_path):
                data = cache_path.read_text(encoding="utf-8")
                log.debug(f"磁盘缓存命中 | path={cache_path.name}")
                return data
        except Exception as e:
            log.warning(f"读取磁盘缓存失败: {e}")
        return None
    
    async def _save_to_disk_cache(self, cache_path: Path, data: str):
        """保存到磁盘缓存"""
        try:
            # 检查缓存目录大小
            await self._cleanup_cache_if_needed()
            cache_path.write_text(data, encoding="utf-8")
            log.debug(f"已保存到磁盘缓存 | path={cache_path.name}")
        except Exception as e:
            log.warning(f"保存磁盘缓存失败: {e}")
    
    async def _cleanup_cache_if_needed(self):
        """清理缓存（如果超出大小限制）"""
        try:
            total_size = sum(f.stat().st_size for f in self.cache_dir.glob("*.cache"))
            max_size_bytes = self.max_cache_size_mb * 1024 * 1024
            
            if total_size > max_size_bytes:
                log.info(f"缓存大小超限({total_size / 1024 / 1024:.1f}MB)，开始清理...")
                # 按修改时间排序，删除最旧的文件
                files = sorted(
                    self.cache_dir.glob("*.cache"),
                    key=lambda f: f.stat().st_mtime
                )
                
                while total_size > max_size_bytes * 0.8 and files:  # 清理到 80%
                    oldest = files.pop(0)
                    total_size -= oldest.stat().st_size
                    oldest.unlink()
                    log.debug(f"删除缓存文件 | {oldest.name}")
        except Exception as e:
            log.warning(f"清理缓存失败: {e}")
    
    def _detect_mime_type(self, url: str, content_type: Optional[str] = None, is_gif_converted: bool = False) -> str:
        """检测 MIME 类型
        
        Args:
            url: 图片 URL
            content_type: HTTP 响应的 Content-Type 头
            is_gif_converted: 是否经过 GIF 转 PNG 转换
            
        Returns:
            MIME 类型字符串
        """
        # [GIF 转换处理] 如果是 GIF 转换后的图片，强制返回 PNG
        # 因为 Gemini API 不支持 image/gif
        if is_gif_converted:
            return "image/png"
        
        # 优先使用 Content-Type
        if content_type:
            if "jpeg" in content_type or "jpg" in content_type:
                return "image/jpeg"
            elif "png" in content_type:
                return "image/png"
            elif "gif" in content_type:
                # [重要] GIF 格式不被 Gemini 支持，这里不应该到达
                # 因为 GIF 应该在下载时就被转换了
                log.warning("检测到 GIF MIME 类型，但未标记为已转换，可能存在逻辑问题")
                return "image/png"  # 保守处理，假设已转换
            elif "webp" in content_type:
                return "image/webp"
        
        # 从 URL 路径推断
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        for ext, mime in MIME_TYPES.items():
            if path_lower.endswith(ext):
                # [重要] GIF 格式不被 Gemini 支持
                if mime == "image/gif":
                    log.warning("从 URL 推断出 GIF 格式，但未标记为已转换")
                    return "image/png"  # 保守处理
                return mime
        
        # 默认 JPEG
        return "image/jpeg"
    
    async def download_and_encode(self, url: str) -> Tuple[str, str]:
        """
        下载图片并编码为 Base64
        
        Args:
            url: 图片 URL
            
        Returns:
            (base64_data, mime_type) 元组
            
        Raises:
            ImageProcessError: 处理失败
        """
        url_hash = self._get_url_hash(url)[:8]
        log.debug(f"开始处理图片 | url_hash={url_hash}")

        # 基础 SSRF 防护：拒绝明显危险 URL（默认更安全）
        _validate_source_url(url)
        
        # 1. 检查内存缓存
        cached = self._get_from_memory_cache(url)
        if cached:
            #缓存格式: "data:mime_type;base64,..."
            if cached.startswith("data:"):
                parts = cached.split(",", 1)
                mime = parts[0].split(":")[1].split(";")[0]
                return parts[1], mime
            return cached, "image/jpeg"
        
        # 2. 检查磁盘缓存
        cache_path = self._get_cache_path(url)
        disk_cached = await self._load_from_disk_cache(cache_path)
        if disk_cached:
            self._set_memory_cache(url, disk_cached)
            if disk_cached.startswith("data:"):
                parts = disk_cached.split(",", 1)
                mime = parts[0].split(":")[1].split(";")[0]
                return parts[1], mime
            return disk_cached, "image/jpeg"
        
        # 3. 下载图片
        try:
            async with self._download_semaphore:
                client = await self._get_client()
            
                # 处理特殊 URL（如 GIF 转换）
                download_url = url
                is_gif_converted = False
                allow_remote_gif_convert = os.getenv("GEMINI_ALLOW_WSRV_GIF_CONVERT", "0").lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }

                # 检测 GIF 格式（通过 URL 扩展名或 Content-Type）
                # 注意：某些 URL 可能没有扩展名，需要在响应头中检测
                if url.lower().endswith(".gif"):
                    # 默认不把原始 URL 发送给第三方转换服务（隐私风险）
                    if allow_remote_gif_convert:
                        download_url = f"https://wsrv.nl/?url={quote(url)}&output=png"
                        log.debug(f"GIF 远程转换(显式启用) | url_hash={url_hash}")
                        is_gif_converted = True
            
                # 使用 stream 模式以检查文件大小
                max_bytes = self.max_image_size_mb * 1024 * 1024
                async with client.stream("GET", download_url, follow_redirects=True) as response:
                    response.raise_for_status()

                    # 重定向后也做一次基础校验（避免跳转到本地地址）
                    _validate_source_url(str(response.url))

                    content_type_header = response.headers.get("content-type", "")
                    is_gif_response = "gif" in content_type_header.lower()

                    # 1. 检查 Content-Length 头
                    content_length_header = response.headers.get("content-length")
                    if content_length_header:
                        if int(content_length_header) > max_bytes:
                            raise ImageProcessError(
                                f"图片过大 (Header: {int(content_length_header)/1024/1024:.1f}MB > {self.max_image_size_mb}MB)"
                            )

                    # 2. 读取内容（带最大值限制）
                    # 注意：如果服务器未返回 Content-Length，我们需要一边读一边计算
                    buf = BytesIO()
                    downloaded = 0
                    async for chunk in response.aiter_bytes():
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            raise ImageProcessError(f"图片过大 (已下载 > {self.max_image_size_mb}MB)")
                        buf.write(chunk)

                    content = buf.getvalue()

                # GIF 逻辑：若响应是 GIF 且未转换，尝试本地转换；失败则明确报错交给上层 fallback
                if (".gif" in url.lower() or is_gif_response) and not is_gif_converted:
                    try:
                        from PIL import Image  # type: ignore

                        img = Image.open(BytesIO(content))
                        out = BytesIO()
                        # 取第一帧，转为 PNG（Gemini 不支持 image/gif）
                        img.seek(0)
                        img.convert("RGBA").save(out, format="PNG")
                        content = out.getvalue()
                        is_gif_converted = True
                        log.debug(f"GIF 本地转换成功 | url_hash={url_hash}")
                    except ImportError:
                        raise ImageProcessError("GIF 需要转换但 Pillow 未安装")
                    except Exception as e:
                        raise ImageProcessError(f"GIF 本地转换失败: {e}")
                
                # 检查最终大小
            content_length = len(content)

            # 获取 MIME 类型（传递 GIF 转换标志）
            # 注意：headers 在下载阶段已读取，这里使用缓存的 content_type_header
            mime_type = self._detect_mime_type(url, content_type_header, is_gif_converted=is_gif_converted)
            
            # 编码为 Base64
            base64_data = base64.b64encode(content).decode("utf-8")
            
            # 构建Data URL格式用于缓存
            data_url = f"data:{mime_type};base64,{base64_data}"
            
            # 保存到缓存
            self._set_memory_cache(url, data_url)
            await self._save_to_disk_cache(cache_path, data_url)
            
            log.success(
                f"图片处理完成 | url_hash={url_hash} | size={content_length/1024:.1f}KB | mime={mime_type}"
            )
            
            return base64_data, mime_type
            
        except httpx.TimeoutException:
            raise ImageProcessError("图片下载超时")
        except httpx.HTTPStatusError as e:
            raise ImageProcessError(f"图片下载失败 (HTTP {e.response.status_code})")
        except Exception as e:
            raise ImageProcessError(f"图片处理失败: {str(e)}")
    
    async def process_images(
        self,
        urls: list[str],
        fallback_to_url: bool = True
    ) -> list[Dict[str, Any]]:
        """
        批量处理图片，返回 OpenAI 格式的图片内容列表
        
        Args:
            urls: 图片 URL 列表
            fallback_to_url: 处理失败时是否回退到 URL 模式
            
        Returns:
            OpenAI 格式的图片内容列表
        """
        results = []
        
        for i, url in enumerate(urls):
            try:
                base64_data, mime_type = await self.download_and_encode(url)
                results.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64_data}"
                    }
                })
                log.debug(f"图片 {i+1}/{len(urls)} 处理成功 (Base64)")
                
            except ImageProcessError as e:
                log.warning(f"图片 {i+1}/{len(urls)} 处理失败: {e}")
                if fallback_to_url:
                    # 回退到 URL 模式
                    log.debug(f"回退到 URL 模式 | url={url[:50]}...")
                    results.append({
                        "type": "image_url",
                        "image_url": {"url": url}
                    })
                else:
                    # 添加错误占位符
                    results.append({
                        "type": "text",
                        "text": f"[图片 {i+1} 加载失败: {str(e)}]"
                    })
        
        return results
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        try:
            cache_files = list(self.cache_dir.glob("*.cache"))
            total_size = sum(f.stat().st_size for f in cache_files)
            
            return {
                "memory_cache_items": len(self._memory_cache),
                "disk_cache_files": len(cache_files),
                "disk_cache_size_mb": total_size / 1024 / 1024,
                "cache_dir": str(self.cache_dir)
            }
        except Exception as e:
            return {"error": str(e)}


# 全局单例
_image_processor: Optional[ImageProcessor] = None


def get_image_processor(max_concurrency: int = 3) -> ImageProcessor:
    """获取图片处理器单例"""
    global _image_processor
    if _image_processor is None:
        _image_processor = ImageProcessor(max_concurrency=max_concurrency)
    return _image_processor


async def close_image_processor() -> None:
    """关闭图片处理器单例（释放 httpx client 等资源）。"""
    global _image_processor
    if _image_processor is None:
        return
    try:
        await _image_processor.close()
    finally:
        _image_processor = None


def extract_images(message: Any, max_images: int) -> list[str]:
    """从消息中提取图片 URL
    
    Args:
        message: NoneBot 消息对象
        max_images: 最大提取图片数量
        
    Returns:
        图片 URL 列表
    """
    if max_images <= 0:
        return []

    urls: list[str] = []
    try:
        segments = message or []
        for seg in segments:
            if len(urls) >= max_images:
                break

            if isinstance(seg, dict):
                seg_type = seg.get("type")
                seg_data = seg.get("data") or {}
            else:
                seg_type = getattr(seg, "type", None)
                seg_data = getattr(seg, "data", {}) or {}

            if str(seg_type or "") != "image":
                continue

            url = str(seg_data.get("url") or "").strip()
            if not url:
                url = str(seg_data.get("file") or "").strip()

            # 这里只接受 http(s) URL；其它标识（例如 v12 的 file_id）
            # 会在上层链路里 best-effort 解析。
            if url.startswith("http://") or url.startswith("https://"):
                urls.append(url)
    except Exception:
        return []

    return urls


def extract_image_file_ids(message: Any, max_images: int) -> list[str]:
    """从消息段中提取 OneBot v12 的图片 file_id（best-effort）。

    - 最多返回 ``max_images`` 个
    - 去重但保持顺序
    """
    if max_images <= 0:
        return []

    file_ids: list[str] = []
    try:
        segments = message or []
        for seg in segments:
            if len(file_ids) >= max_images:
                break

            if isinstance(seg, dict):
                seg_type = seg.get("type")
                seg_data = seg.get("data") or {}
            else:
                seg_type = getattr(seg, "type", None)
                seg_data = getattr(seg, "data", {}) or {}

            if str(seg_type or "") != "image":
                continue

            file_id = seg_data.get("file_id")
            if not file_id:
                continue

            file_id_str = str(file_id).strip()
            if file_id_str and file_id_str not in file_ids:
                file_ids.append(file_id_str)
    except Exception:
        return []

    return file_ids


async def resolve_image_urls(bot: Any, message: Any, max_images: int) -> list[str]:
    """跨 OneBot 实现解析图片 URL（best-effort）。

    解析策略：
    1) 先通过 :func:`extract_images` 提取消息段里直接给出的 http(s) URL
    2) 若数量不足，再尝试 OneBot v12 的 ``get_file``，把仅提供 ``file_id`` 的图片解析成 URL
    """
    from .safe_api import safe_call_api

    urls = extract_images(message, max_images=max_images)
    if not bot or max_images <= 0 or len(urls) >= max_images:
        return urls

    remaining = max_images - len(urls)
    file_ids = extract_image_file_ids(message, max_images=remaining)
    if not file_ids:
        return urls

    for file_id in file_ids:
        res = await safe_call_api(bot, "get_file", file_id=file_id)
        if not isinstance(res, dict):
            continue
        url = str(res.get("url") or res.get("download_url") or "").strip()
        if url.startswith("http://") or url.startswith("https://"):
            if url not in urls:
                urls.append(url)
                if len(urls) >= max_images:
                    break

    return urls
