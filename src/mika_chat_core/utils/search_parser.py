"""搜索结果解析与格式化模块。

提供搜索结果的过滤、排序和格式化功能（无网络调用、无全局状态）：
- 可信来源优先排序
- 结果去重与过滤
- 注入文本构建（供 LLM 上下文使用）

相关模块：
- [`search_engine`](search_engine.py:1): 搜索主入口
- [`search_cache`](search_cache.py:1): 结果缓存
"""

from __future__ import annotations

from typing import Dict, List, Sequence
from urllib.parse import urlparse


def is_trusted_source(url: str, trusted_domains: Sequence[str]) -> bool:
    """检查链接是否来自可信来源。"""

    url_lower = (url or "").lower()
    for domain in trusted_domains:
        if domain in url_lower:
            return True
    return False


def sort_by_relevance(results: List[Dict], trusted_domains: Sequence[str]) -> List[Dict]:
    """按可信度排序搜索结果，可信来源优先展示。"""

    trusted: List[Dict] = []
    others: List[Dict] = []

    for res in results:
        link = res.get("link", "")
        if is_trusted_source(link, trusted_domains):
            trusted.append(res)
        else:
            others.append(res)

    return trusted + others


def filter_search_results(
    results: List[Dict],
    *,
    max_results: int,
    trusted_domains: Sequence[str],
) -> List[Dict]:
    """过滤无效/低质量结果并限制 Top-N。"""

    filtered: List[Dict] = []
    for res in results:
        title = str(res.get("title", "") or "").strip()
        link = str(res.get("link", "") or "").strip()
        snippet = str(res.get("snippet", "") or "").strip()

        if not title or not link or not snippet:
            continue

        parsed = urlparse(link)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue

        filtered.append({"title": title, "link": link, "snippet": snippet})

    if not filtered:
        return []

    sorted_results = sort_by_relevance(filtered, trusted_domains)
    return sorted_results[: max(1, max_results)]


def build_injection_content(
    filtered_results: List[Dict],
    *,
    trusted_domains: Sequence[str],
    header_tmpl: str,
    item_tmpl: str,
    footer_tmpl: str,
    current_time_str: str,
) -> str:
    """构建注入到 LLM 上下文的格式化文本。"""

    parts: List[str] = []
    parts.append(header_tmpl.format(current_time=current_time_str).strip())

    for i, res in enumerate(filtered_results, 1):
        title = res.get("title", "")
        link = res.get("link", "")
        snippet = res.get("snippet", "")

        trust_tag = "★" if is_trusted_source(link, trusted_domains) else ""

        try:
            item_str = item_tmpl.format(
                index=i,
                trust_tag=trust_tag,
                title=title,
                snippet=snippet,
                link=link,
            )
            parts.append(item_str)
        except Exception:
            parts.append(f"{i}. {title} (格式化失败)")

    parts.append(footer_tmpl.strip())
    return "\n".join(parts)

