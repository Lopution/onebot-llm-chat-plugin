"""Mika API - API Key 轮换与冷却策略。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple


def select_api_key(
    *,
    api_key: str,
    api_key_list: List[str],
    key_index: int,
    key_cooldowns: Dict[str, float],
    log_obj: Any,
) -> Tuple[str, int]:
    """根据轮询与冷却状态选择一个可用 API Key。"""
    current_time = time.monotonic()

    if not api_key_list:
        return api_key, key_index

    all_keys = list(api_key_list)
    attempts = 0
    max_attempts = len(all_keys)
    next_index = int(key_index)

    while attempts < max_attempts:
        key = all_keys[next_index]
        next_index = (next_index + 1) % len(all_keys)
        attempts += 1

        cooldown_end = key_cooldowns.get(key, 0)
        if current_time >= cooldown_end:
            if key in key_cooldowns:
                del key_cooldowns[key]
                log_obj.debug(f"API Key #{next_index} 冷却期结束，恢复使用")
            return key, next_index

        remaining = int(cooldown_end - current_time)
        log_obj.debug(f"API Key #{next_index} 仍在冷却中（剩余 {remaining}s），跳过")

    min_cooldown_key = min(all_keys, key=lambda item: key_cooldowns.get(item, 0))
    log_obj.warning("所有 API Key 都在冷却期，强制使用冷却时间最短的 Key")
    return min_cooldown_key, next_index


def mark_key_rate_limited(
    *,
    key: str,
    retry_after: int,
    default_cooldown: int,
    key_cooldowns: Dict[str, float],
    log_obj: Any,
) -> None:
    """记录 key 限流冷却时间。"""
    cooldown_seconds = int(retry_after) if int(retry_after or 0) > 0 else int(default_cooldown)
    key_cooldowns[str(key)] = time.monotonic() + cooldown_seconds
    log_obj.warning(f"API Key 被限流，进入冷却期 {cooldown_seconds}s")
