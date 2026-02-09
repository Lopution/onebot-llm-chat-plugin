"""Gemini Chat 搜索引擎（主入口模块）。

本文件是对外的稳定入口，外部代码通过本模块导入相关函数/常量。

为降低维护成本，本模块已将职责拆分到多个子模块：
- [`search_client`](search_client.py:1): HTTP 客户端默认配置
- [`search_cache`](search_cache.py:1): 搜索结果缓存
- [`search_parser`](search_parser.py:1): 结果过滤/可信排序/注入文本构建
- [`search_classifier`](search_classifier.py:1): query 清洗/低信号过滤/LLM 分类

注意：
- 为保持向后兼容，本模块保留原有公开 API 名称与全局变量
- 缓存字典由本模块持有，以兼容测试 patch
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable

import asyncio
import httpx
import os
import time

from ..infra.logging import logger as log

from ..metrics import metrics
from ..config import plugin_config
from .prompt_loader import load_search_prompt

from . import search_cache as _search_cache_impl
from .search_client import create_default_http_client
from .search_parser import (
    build_injection_content as _build_injection_content,
    filter_search_results as _filter_search_results_impl,
    is_trusted_source as _is_trusted_source_impl,
    sort_by_relevance as _sort_by_relevance_impl,
)

# 重新导出分类/清洗相关逻辑（对外接口保持不变）
from .search_classifier import (  # noqa: F401
    AI_KEYWORDS,
    BEST_KEYWORDS,
    LOW_SIGNAL_TOKENS,
    QUESTION_KEYWORDS,
    TIMELINESS_KEYWORDS,
    WEAK_TIME_KEYWORDS,
    _extract_json_object,
    classify_topic_for_search,
    clear_classify_cache,
    is_local_datetime_query,
    is_low_signal_query,
    normalize_search_query,
    should_fallback_strong_timeliness,
    should_search,
)


# ============================================================
# 搜索结果数据类和提供者协议
# ============================================================


@dataclass
class SearchResult:
    """搜索结果数据类。

    用于统一表示来自不同搜索引擎的结果。
    """

    title: str
    url: str
    snippet: str
    source: str = ""


@runtime_checkable
class SearchProvider(Protocol):
    """搜索提供者协议。"""

    async def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        ...


# ============================================================
# 常量与全局状态（保留以兼容旧代码 / tests patch）
# ============================================================


TRUSTED_DOMAINS = [
    # 综合知识
    "wikipedia.org",
    "zhihu.com",
    "36kr.com",
    "sspai.com",
    # 技术/学术
    "github.com",
    "arxiv.org",
    "nature.com",
    "science.org",
    # 新闻媒体
    "reuters.com",
    "bbc.com",
    "nytimes.com",
    "theverge.com",
    "techcrunch.com",
    "arstechnica.com",
    "wired.com",
    # AI/科技公司
    "openai.com",
    "anthropic.com",
    "google.com",
    "microsoft.com",
    "huggingface.co",
    "pytorch.org",
    "tensorflow.org",
    # 电竞/游戏媒体
    "lolesports.com",
    "lpl.qq.com",
    "score.gg",
    "gol.gg",
    "liquipedia.net",
    "dongqiudi.com",
    "hupu.com",
    "bilibili.com",
    "weibo.com",
    "douyin.com",
]


# 兼容旧 tests / 旧接口的常量名
TIME_SENSITIVE_KEYWORDS = TIMELINESS_KEYWORDS


# Serper API Key（从 NoneBot 配置获取）
SERPER_API_KEY: Optional[str] = None
TAVILY_API_KEY: Optional[str] = None
SEARCH_PROVIDER_NAME: str = "serper"
SEARCH_EXTRA_HEADERS: Dict[str, str] = {}

# 全局 HTTP 客户端（复用连接池，提高性能）
_http_client: Optional[httpx.AsyncClient] = None
_http_client_lock: asyncio.Lock = asyncio.Lock()

# 搜索结果缓存（避免短时间内重复搜索）
# 格式: {query_hash: (result, timestamp)}
_search_cache: Dict[str, Tuple[str, float]] = {}
# 默认值（可由 lifecycle.configure_search_cache 在启动时覆写）
CACHE_TTL_SECONDS = 60  # 缓存有效期：1分钟（时效性查询需要更短缓存）
MAX_CACHE_SIZE = 100  # 最大缓存条目数

# Serper 搜索 query 增强
DEFAULT_TIME_KEYWORDS = ["最新", "今天", "现在", "目前", "刚刚", "最近"]
DEFAULT_ENHANCE_SUFFIX = " 最新"

# 搜索结果日志预览
QUERY_PREVIEW_CHARS = 30
SNIPPET_PREVIEW_CHARS = 100
LOG_SEPARATOR_WIDTH = 50

# 注入结果条数限制范围（安全兜底）
MIN_INJECTION_RESULTS = 1
MAX_INJECTION_RESULTS = 10
DEFAULT_INJECTION_RESULTS = 6


# ============================================================
# 缓存（保持原私有函数名不变）
# ============================================================


def _get_cache_key(query: str) -> str:
    """生成缓存键（对查询进行哈希）。"""

    return _search_cache_impl.make_cache_key(query)


def _get_cached_result(query: str) -> Optional[str]:
    """获取缓存的搜索结果。"""

    cached = _search_cache_impl.get_cached_result(
        _search_cache,
        query=query,
        ttl_seconds=CACHE_TTL_SECONDS,
    )
    if cached is not None:
        log.debug(f"缓存命中: {query[:QUERY_PREVIEW_CHARS]}...")
        return cached
    return None


def _set_cache(query: str, result: str) -> None:
    """缓存搜索结果。"""

    global _search_cache
    before = len(_search_cache)

    _search_cache_impl.set_cached_result(
        _search_cache,
        query=query,
        result=result,
        max_size=MAX_CACHE_SIZE,
    )

    after = len(_search_cache)
    if after < before:
        log.debug("缓存已满，移除最旧条目")
    log.debug(f"已缓存搜索结果: {query[:QUERY_PREVIEW_CHARS]}...")


def clear_search_cache() -> None:
    """清空搜索缓存。"""

    global _search_cache
    _search_cache = {}
    log.info("搜索缓存已清空")


def configure_search_cache(ttl_seconds: int, max_size: int) -> None:
    """配置搜索缓存参数。"""

    global CACHE_TTL_SECONDS, MAX_CACHE_SIZE
    CACHE_TTL_SECONDS = max(5, int(ttl_seconds))
    MAX_CACHE_SIZE = max(10, int(max_size))
    log.info(f"搜索缓存配置已更新 | ttl={CACHE_TTL_SECONDS}s | max_size={MAX_CACHE_SIZE}")


def configure_classify_cache(ttl_seconds: int, max_size: int) -> None:
    """配置 LLM 分类判定缓存参数。

    说明：分类缓存的 TTL/容量读取逻辑在
    [`search_classifier`](mika_chat_core/utils/search_classifier.py:1)
    中；此函数仅用于启动日志提示（保留旧接口）。
    """

    ttl = max(5, int(ttl_seconds))
    size = max(10, int(max_size))
    log.info(f"分类判定缓存配置已更新 | ttl={ttl}s | max_size={size}")


# ============================================================
# HTTP 客户端生命周期
# ============================================================


async def _get_http_client() -> httpx.AsyncClient:
    """获取或创建全局 HTTP 客户端。"""

    global _http_client
    async with _http_client_lock:
        if _http_client is None or _http_client.is_closed:
            _http_client = create_default_http_client()
            log.debug("创建新的 HTTP 客户端")
        return _http_client


async def init_search_engine() -> None:
    """启动时初始化搜索引擎（加载配置和创建 HTTP 客户端）。"""

    global SERPER_API_KEY, TAVILY_API_KEY, SEARCH_PROVIDER_NAME, SEARCH_EXTRA_HEADERS, _search_provider
    cfg = plugin_config.get_search_provider_config()
    SEARCH_PROVIDER_NAME = str(cfg.get("provider") or "serper").strip().lower()
    SEARCH_EXTRA_HEADERS = dict(cfg.get("extra_headers") or {})
    _search_provider = None

    configured_key = str(cfg.get("api_key") or "").strip()
    SERPER_API_KEY = ""
    TAVILY_API_KEY = ""
    if SEARCH_PROVIDER_NAME == "tavily":
        TAVILY_API_KEY = configured_key or os.getenv("TAVILY_API_KEY", "")
        if TAVILY_API_KEY:
            log.success("Tavily API Key 加载成功")
        else:
            log.warning("未找到 TAVILY_API_KEY，搜索功能将被禁用")
    else:
        legacy_serper_key = str(getattr(plugin_config, "serper_api_key", "") or "").strip()
        SERPER_API_KEY = configured_key or legacy_serper_key or os.getenv("SERPER_API_KEY", "")
        SEARCH_PROVIDER_NAME = "serper"
        if SERPER_API_KEY:
            log.success("Serper API Key 加载成功")
        else:
            log.warning("未找到 SERPER_API_KEY，搜索功能将被禁用")

    await _get_http_client()
    log.success("HTTP 客户端初始化完成")


async def close_search_engine() -> None:
    """关闭时清理 HTTP 客户端。"""

    global _http_client
    async with _http_client_lock:
        if _http_client and not _http_client.is_closed:
            await _http_client.aclose()
            _http_client = None
            log.info("HTTP 客户端已关闭")
    _http_client = None


# ============================================================
# 结果解析/排序（对外 API 保持不变）
# ============================================================


def is_trusted_source(url: str) -> bool:
    """检查链接是否来自可信来源。"""

    return _is_trusted_source_impl(url, TRUSTED_DOMAINS)


def sort_by_relevance(results: List[Dict]) -> List[Dict]:
    """按可信度排序搜索结果，可信来源优先展示。"""

    return _sort_by_relevance_impl(results, TRUSTED_DOMAINS)


def _filter_search_results(results: List[Dict], max_results: int) -> List[Dict]:
    """过滤无效/低质量结果并限制 Top-N。"""

    return _filter_search_results_impl(
        results,
        max_results=max_results,
        trusted_domains=TRUSTED_DOMAINS,
    )


def _get_max_injection_results() -> int:
    """从配置读取注入结果上限（提供安全兜底）。"""

    try:
        value = int(getattr(plugin_config, "gemini_search_max_injection_results", DEFAULT_INJECTION_RESULTS))
        return max(MIN_INJECTION_RESULTS, min(MAX_INJECTION_RESULTS, value))
    except Exception:
        return DEFAULT_INJECTION_RESULTS


# ============================================================
# Serper 搜索（网络请求 + 注入文本构建）
# ============================================================


async def serper_search(query: str, max_results: int = 8) -> str:
    """使用 Serper.dev API 执行 Google 搜索并返回格式化结果。"""
    provider = get_search_provider()
    if provider is None:
        log.warning("搜索 provider 未配置，跳过搜索")
        return ""

    clean_query = normalize_search_query(query)
    if is_low_signal_query(clean_query):
        log.debug(f"搜索 query 低信号过滤: '{query[:QUERY_PREVIEW_CHARS]}'")
        return ""

    # 本地时间/日期问题不执行外部搜索（避免不可靠结果）
    if is_local_datetime_query(clean_query):
        log.debug(f"搜索 query 本地时间/日期过滤: '{query[:QUERY_PREVIEW_CHARS]}'")
        return ""

    has_time_keyword = any(kw in clean_query for kw in DEFAULT_TIME_KEYWORDS)
    enhanced_query = clean_query if has_time_keyword else f"{clean_query}{DEFAULT_ENHANCE_SUFFIX}"

    cached_result = _get_cached_result(enhanced_query)
    if cached_result is not None:
        metrics.search_cache_hit_total += 1
        log.info(f"使用缓存结果: '{query[:QUERY_PREVIEW_CHARS]}...'")
        return cached_result
    metrics.search_cache_miss_total += 1

    metrics.search_requests_total += 1
    log.info(f"执行 {type(provider).__name__} 搜索: '{query}'")

    try:
        provider_results = await provider.search(enhanced_query, num_results=max_results)
        if not provider_results:
            log.warning(f"未找到搜索结果: {query}")
            return ""

        organic_results: List[Dict[str, str]] = []
        for item in provider_results:
            organic_results.append(
                {
                    "title": item.title,
                    "link": item.url,
                    "snippet": item.snippet,
                }
            )

        limit = max(1, min(_get_max_injection_results(), max_results))
        filtered_results = _filter_search_results(organic_results, limit)
        if not filtered_results:
            log.warning(f"过滤后无有效结果: {query}")
            return ""

        # 加载注入模板（tests 会 patch 本模块的 `load_search_prompt`）
        search_config = load_search_prompt()
        if not isinstance(search_config, dict):
            log.warning(
                f"[SearchEngine] search.yaml root 应为 dict，实际为 {type(search_config).__name__}，已使用默认注入模板"
            )
            search_config = {}

        injection_templates = search_config.get("result_injection", {})
        if not isinstance(injection_templates, dict):
            log.warning(
                f"[SearchEngine] result_injection 应为 dict，实际为 {type(injection_templates).__name__}，已使用默认注入模板"
            )
            injection_templates = {}

        header_tmpl = injection_templates.get(
            "header",
            "--- [实时事实注入] ---\n查询时间: {current_time}\n以下是基于 Google 搜索的最新事实（按可信度排序）：",
        )
        item_tmpl = injection_templates.get(
            "item_template",
            "{index}. {trust_tag}【{title}】\n   摘要: {snippet}\n   来源: {link}",
        )
        footer_tmpl = injection_templates.get(
            "footer",
            "--- [注入结束] ---\n提示: 带★的结果来自可信来源，请优先参考。如果搜索结果与问题不相关，请坦诚告知。",
        )

        # 详细日志（保持原行为）
        log.debug("=" * LOG_SEPARATOR_WIDTH)
        log.debug("搜索结果详情：")
        for i, res in enumerate(filtered_results, 1):
            title = res.get("title", "")
            link = res.get("link", "")
            snippet = res.get("snippet", "")
            trust_tag = "★" if is_trusted_source(link) else ""
            log.debug(f"[{i}] {trust_tag}{title}")
            log.debug(
                f"    摘要: {snippet[:SNIPPET_PREVIEW_CHARS]}..."
                if len(snippet) > SNIPPET_PREVIEW_CHARS
                else f"    摘要: {snippet}"
            )
            log.debug(f"    来源: {link}")
        log.debug("=" * LOG_SEPARATOR_WIDTH)

        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        injection_content = _build_injection_content(
            filtered_results,
            trusted_domains=TRUSTED_DOMAINS,
            header_tmpl=header_tmpl,
            item_tmpl=item_tmpl,
            footer_tmpl=footer_tmpl,
            current_time_str=current_time_str,
        )

        log.success(f"搜索成功，获取 {len(filtered_results)} 条结果")
        log.debug(f"完整注入内容:\n{injection_content}")

        _set_cache(enhanced_query, injection_content)
        return injection_content

    except Exception as e:
        log.error(f"搜索请求错误: {str(e)}", exc_info=True)
        return ""


async def google_search(query: str, api_key: str = "", cx: str = "") -> str:
    """向后兼容接口，实际调用 Serper。"""

    return await serper_search(query)


# ============================================================
# 搜索提供者实现
# ============================================================


class SerperProvider:
    """Serper API 搜索提供者。"""

    def __init__(self, api_key: str, extra_headers: Optional[Dict[str, str]] = None):
        self.api_key = api_key
        self.extra_headers = dict(extra_headers or {})

    async def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        if not self.api_key:
            log.warning("SerperProvider: API Key 未配置")
            return []

        clean_query = normalize_search_query(query)
        if is_low_signal_query(clean_query):
            log.debug(f"SerperProvider 低信号过滤: '{query[:QUERY_PREVIEW_CHARS]}'")
            return []

        log.debug(f"SerperProvider 搜索: '{clean_query}' (num={num_results})")
        try:
            client = await _get_http_client()
            response = await client.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": self.api_key,
                    "Content-Type": "application/json",
                    **self.extra_headers,
                },
                json={
                    "q": clean_query,
                    "gl": "cn",
                    "hl": "zh-cn",
                    "num": num_results,
                },
            )
            response.raise_for_status()
            data = response.json()
            organic_results = data.get("organic", [])
            if not organic_results:
                log.debug(f"SerperProvider: 无结果 for '{query}'")
                return []

            filtered_results = _filter_search_results(organic_results, num_results)
            if not filtered_results:
                log.debug(f"SerperProvider: 过滤后无有效结果 for '{query}'")
                return []

            results: List[SearchResult] = []
            for item in filtered_results:
                results.append(
                    SearchResult(
                        title=str(item.get("title", "")),
                        url=str(item.get("link", "")),
                        snippet=str(item.get("snippet", "")),
                        source="serper",
                    )
                )
            return results
        except httpx.TimeoutException:
            log.warning("SerperProvider: 请求超时")
            return []
        except httpx.ConnectError as exc:
            log.warning(f"SerperProvider: 连接失败: {exc}")
            return []
        except Exception as exc:
            log.error(f"SerperProvider: 搜索错误: {exc}", exc_info=True)
            return []


class TavilyProvider:
    """Tavily 搜索提供者。"""

    def __init__(self, api_key: str, extra_headers: Optional[Dict[str, str]] = None):
        self.api_key = api_key
        self.extra_headers = dict(extra_headers or {})

    async def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        if not self.api_key:
            log.warning("TavilyProvider: API Key 未配置")
            return []

        clean_query = normalize_search_query(query)
        if is_low_signal_query(clean_query):
            log.debug(f"TavilyProvider 低信号过滤: '{query[:QUERY_PREVIEW_CHARS]}'")
            return []

        try:
            client = await _get_http_client()
            response = await client.post(
                "https://api.tavily.com/search",
                headers={"Content-Type": "application/json", **self.extra_headers},
                json={
                    "api_key": self.api_key,
                    "query": clean_query,
                    "max_results": num_results,
                    "search_depth": "basic",
                    "include_answer": False,
                    "include_raw_content": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            raw_results = data.get("results", [])
            if not isinstance(raw_results, list) or not raw_results:
                return []

            results: List[SearchResult] = []
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                results.append(
                    SearchResult(
                        title=str(item.get("title") or ""),
                        url=str(item.get("url") or ""),
                        snippet=str(item.get("content") or item.get("snippet") or ""),
                        source="tavily",
                    )
                )
            return results
        except httpx.TimeoutException:
            log.warning("TavilyProvider: 请求超时")
            return []
        except httpx.ConnectError as exc:
            log.warning(f"TavilyProvider: 连接失败: {exc}")
            return []
        except Exception as exc:
            log.error(f"TavilyProvider: 搜索错误: {exc}", exc_info=True)
            return []


_search_provider: Optional[SearchProvider] = None


def get_search_provider() -> Optional[SearchProvider]:
    """获取当前配置的搜索提供者。"""

    global _search_provider

    if _search_provider is not None:
        return _search_provider

    if SEARCH_PROVIDER_NAME == "tavily":
        if TAVILY_API_KEY:
            _search_provider = TavilyProvider(api_key=TAVILY_API_KEY, extra_headers=SEARCH_EXTRA_HEADERS)
            log.info("搜索提供者: TavilyProvider")
            return _search_provider
        log.warning("TavilyProvider 未启用：缺少 API Key")
        return None

    if SERPER_API_KEY:
        _search_provider = SerperProvider(api_key=SERPER_API_KEY, extra_headers=SEARCH_EXTRA_HEADERS)
        log.info("搜索提供者: SerperProvider")
        return _search_provider

    log.warning("无可用的搜索提供者（缺少可用 API Key）")
    return None


def set_search_provider(provider: SearchProvider) -> None:
    """手动设置搜索提供者（用于测试或自定义后端）。"""

    global _search_provider
    _search_provider = provider
    log.info(f"搜索提供者已设置: {type(provider).__name__}")


def reset_search_provider() -> None:
    """重置搜索提供者。"""

    global _search_provider
    _search_provider = None
    log.debug("搜索提供者已重置")


async def provider_search(query: str, num_results: int = 5) -> List[SearchResult]:
    """使用当前提供者执行搜索的便捷函数。"""

    provider = get_search_provider()
    if provider is None:
        log.warning("provider_search: 无可用的搜索提供者")
        return []

    return await provider.search(query, num_results)
