"""用户档案 LLM 抽取服务（异步、非阻塞）。

将用户消息增量汇聚后，按门控策略触发 LLM 抽取，并把 delta 合并写入 user_profiles。

设计要点：
- handler 侧只调用 ingest（O(1) 内存操作），不 await LLM
- 后台任务串行处理每个用户，避免并发写档案
- 全局限流 + per-user 冷却，避免成本失控
- 覆盖旧值采用二次确认（pending_overrides 存在 extra_info）

相关模块：
- [`user_profile`](user_profile.py:1): 档案存储
- [`user_profile_llm_extractor`](user_profile_llm_extractor.py:1): LLM 调用
- [`user_profile_merge`](user_profile_merge.py:1): 合并策略
"""

from __future__ import annotations

import asyncio
import time
import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional

from ..infra.logging import logger as log

from ..config import plugin_config
from .session_lock import SessionLockManager
from .user_profile import get_user_profile_store
from .user_profile_llm_extractor import extract_profile_with_llm
from .user_profile_merge import (
    merge_profile_delta,
    build_provenance_extra_info,
)


# ==================== Magic-number constants ====================
GLOBAL_RATE_LIMIT_WINDOW_SECONDS = 60.0
GLOBAL_RATE_LIMIT_TIMESTAMPS_MAXLEN = 2000
GLOBAL_RATE_LIMIT_SLEEP_SECONDS = 10


_TRIGGER_KEYWORDS = [
    # 名字
    "我叫",
    "你可以叫我",
    "我的名字",
    "我的姓名",
    # 关系/身份（用户与机器人）
    "我是你的",
    "你是我的",
    # 偏好
    "我喜欢",
    "我最喜欢",
    "我爱",
    "我讨厌",
    "我不喜欢",
    # 人生信息
    "生日",
    "我今年",
    "我岁",
    "来自",
    "住在",
    "我在",
]


def _looks_like_noise(text: str) -> bool:
    """低成本噪声过滤：明显不是自述信息的内容直接跳过触发。"""
    if not text:
        return True

    t = text.strip()
    # 过短
    if len(t) < plugin_config.profile_extract_min_chars:
        return True
    # 代码块/日志特征（location 误触发常见来源）
    if "```" in t or "Traceback" in t or "Exception" in t:
        return True
    # URL
    if "http://" in t or "https://" in t:
        return True
    return False


def _hit_keywords(text: str) -> bool:
    return any(k in text for k in _TRIGGER_KEYWORDS)


@dataclass
class _UserState:
    buffer: List[Dict[str, Any]]
    msg_count: int
    last_extract_ts: float
    last_seen_ts: float
    inflight: bool


class UserProfileExtractService:
    def __init__(self) -> None:
        self._states: Dict[str, _UserState] = {}
        self._lock_manager = SessionLockManager(max_locks=1024, ttl_seconds=3600.0)

        # 全局调用限流：记录最近 N 秒内的调用时间戳
        self._call_timestamps: Deque[float] = deque(maxlen=GLOBAL_RATE_LIMIT_TIMESTAMPS_MAXLEN)

    def ingest_message(
        self,
        *,
        qq_id: str,
        nickname: str,
        content: str,
        message_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> None:
        """接入一条用户消息（非阻塞）。"""
        # 场景开关
        if group_id is None:
            if not plugin_config.profile_extract_enabled or not plugin_config.profile_extract_enable_private:
                return
        else:
            if not plugin_config.profile_extract_enabled:
                return

        if not content or _looks_like_noise(content):
            return

        now = time.time()
        state = self._states.get(qq_id)
        if state is None:
            state = _UserState(
                buffer=[],
                msg_count=0,
                last_extract_ts=0.0,
                last_seen_ts=now,
                inflight=False,
            )
            self._states[qq_id] = state
        else:
            state.last_seen_ts = now

        state.msg_count += 1

        state.buffer.append(
            {
                "content": content,
                "message_id": str(message_id) if message_id is not None else None,
                "group_id": str(group_id) if group_id is not None else None,
                "nickname": nickname,
                "timestamp": now,
            }
        )

        # 控制窗口
        bw = max(1, int(plugin_config.profile_extract_batch_window))
        if len(state.buffer) > bw:
            state.buffer = state.buffer[-bw:]

        # 防止长期运行无界增长：在 ingest 侧做一次轻量 prune
        self._prune_states(now=now)

        if not self._should_trigger(qq_id=qq_id, content=content):
            return

        self._schedule_extract(qq_id=qq_id, nickname=nickname, group_id=group_id)

    def _should_trigger(self, *, qq_id: str, content: str) -> bool:
        """两级门控：关键词触发 + 每 N 条兜底触发。"""
        state = self._states.get(qq_id)
        if state is None:
            return False

        now = time.time()
        cooldown = max(0, int(plugin_config.profile_extract_cooldown_seconds))
        if state.last_extract_ts and now - state.last_extract_ts < cooldown:
            # 冷却期内仅关键词强触发（减少成本）
            return _hit_keywords(content)

        # Level A：关键词
        if _hit_keywords(content):
            return True

        # Level B：频率兜底
        every_n = max(1, int(plugin_config.profile_extract_every_n_messages))
        return state.msg_count % every_n == 0

    def _schedule_extract(self, *, qq_id: str, nickname: str, group_id: Optional[str]) -> None:
        state = self._states.get(qq_id)
        if state is None:
            return
        if state.inflight:
            return

        # per-user 队列上限：通过 buffer 长度和 inflight 简化控制
        state.inflight = True
        asyncio.create_task(self._extract_task(qq_id=qq_id, nickname=nickname, group_id=group_id))

    def _global_rate_limited(self) -> bool:
        limit = max(1, int(plugin_config.profile_extract_max_calls_per_minute))
        now = time.time()

        # 清理窗口外
        while self._call_timestamps and now - self._call_timestamps[0] > GLOBAL_RATE_LIMIT_WINDOW_SECONDS:
            self._call_timestamps.popleft()

        return len(self._call_timestamps) >= limit

    def _prune_states(self, *, now: float) -> None:
        """清理长期不活跃的 per-user state，防止无界增长。"""
        ttl = max(60, int(getattr(plugin_config, "profile_extract_state_ttl_seconds", 7200) or 7200))
        max_users = max(1, int(getattr(plugin_config, "profile_extract_state_max_users", 1000) or 1000))

        expire_before = now - float(ttl)

        # 1) TTL 清理
        for uid, state in list(self._states.items()):
            if state.inflight:
                continue
            if state.last_seen_ts and state.last_seen_ts < expire_before:
                self._states.pop(uid, None)

        # 2) 上限清理：淘汰最旧的
        if len(self._states) <= max_users:
            return

        items = sorted(self._states.items(), key=lambda kv: kv[1].last_seen_ts or 0.0)
        for uid, state in items:
            if len(self._states) <= max_users:
                break
            if state.inflight:
                continue
            self._states.pop(uid, None)

    async def _extract_task(self, *, qq_id: str, nickname: str, group_id: Optional[str]) -> None:
        lock = self._lock_manager.get_lock(qq_id)
        async with lock:
            state = self._states.get(qq_id)
            if state is None:
                return

            try:
                # 全局限流：如果触顶，延迟重试一次（避免丢失信号）
                if self._global_rate_limited():
                    log.warning(f"[ProfileExtract] 全局限流触发，延迟 {GLOBAL_RATE_LIMIT_SLEEP_SECONDS}s")
                    await asyncio.sleep(GLOBAL_RATE_LIMIT_SLEEP_SECONDS)
                    if self._global_rate_limited():
                        return

                # 取出待处理 buffer（复制后清空，避免处理时持续增长）
                buffer = list(state.buffer)
                state.buffer = []
                state.msg_count = 0

                if not buffer:
                    return

                store = get_user_profile_store()
                existing = await store.get_profile(qq_id)
                existing_extra = existing.get("extra_info") or {}

                pending_overrides = {}
                if isinstance(existing_extra, dict):
                    pending_overrides = existing_extra.get("profile_pending_overrides") or {}

                # 记录调用时间戳
                self._call_timestamps.append(time.time())

                # 调用 LLM
                llm_result = await extract_profile_with_llm(
                    qq_id=qq_id,
                    nickname=nickname,
                    messages=buffer,
                    existing_profile=existing,
                    group_id=str(group_id) if group_id is not None else None,
                )

                if not llm_result.success:
                    log.warning(f"[ProfileExtract] 抽取失败 | qq_id={qq_id} | err={llm_result.error}")
                    if plugin_config.profile_extract_store_audit_events:
                        await store.add_audit_event(
                            qq_id=qq_id,
                            group_id=str(group_id) if group_id is not None else None,
                            scene="group" if group_id is not None else "private",
                            input_messages=buffer,
                            llm_output={"success": False, "error": llm_result.error, "raw": llm_result.raw_response},
                            merge_result={},
                            applied_fields={},
                        )
                    return

                if llm_result.no_update:
                    log.debug(f"[ProfileExtract] 无更新 | qq_id={qq_id}")
                    if plugin_config.profile_extract_store_audit_events:
                        await store.add_audit_event(
                            qq_id=qq_id,
                            group_id=str(group_id) if group_id is not None else None,
                            scene="group" if group_id is not None else "private",
                            input_messages=buffer,
                            llm_output=llm_result.to_dict(),
                            merge_result={"no_update": True},
                            applied_fields={},
                        )
                    return

                # 合并
                merge_res, new_pending = merge_profile_delta(
                    existing_profile=existing,
                    delta=llm_result.delta,
                    evidence=llm_result.evidence,
                    confidence=llm_result.confidence,
                    pending_overrides=pending_overrides if isinstance(pending_overrides, dict) else {},
                    threshold_new=float(plugin_config.profile_extract_threshold_new_field),
                    threshold_override=float(plugin_config.profile_extract_threshold_override_field),
                    require_repeat=bool(plugin_config.profile_extract_override_requires_repeat),
                    extractor_model=plugin_config.profile_extract_model or plugin_config.gemini_fast_model,
                )

                update_fields: Dict[str, Any] = {}
                update_fields.update(merge_res.merged_fields)

                # 维护 extra_info：溯源 + pending_overrides
                if isinstance(existing_extra, str):
                    try:
                        existing_extra = json.loads(existing_extra) if existing_extra else {}
                    except Exception:
                        existing_extra = {}
                if not isinstance(existing_extra, dict):
                    existing_extra = {}

                extra_info = build_provenance_extra_info(existing_extra, merge_res.provenance)
                if new_pending:
                    extra_info["profile_pending_overrides"] = new_pending
                else:
                    # 清理
                    extra_info.pop("profile_pending_overrides", None)

                update_fields["extra_info"] = extra_info

                applied = {}
                if update_fields:
                    applied = update_fields.copy()
                    await store.update_profile(qq_id, update_fields)

                if plugin_config.profile_extract_store_audit_events:
                    await store.add_audit_event(
                        qq_id=qq_id,
                        group_id=str(group_id) if group_id is not None else None,
                        scene="group" if group_id is not None else "private",
                        input_messages=buffer,
                        llm_output=llm_result.to_dict(),
                        merge_result=merge_res.to_dict(),
                        applied_fields=applied,
                    )

                state.last_extract_ts = time.time()
                log.info(
                    f"[ProfileExtract] 完成 | qq_id={qq_id} | applied={list(merge_res.merged_fields.keys())} | pending={list(new_pending.keys())}"
                )

            except Exception as e:
                # 兜底：避免 create_task 的异常逃逸（Task exception was never retrieved）
                # 注意：inflight 释放仍由 finally 保障。
                log.error(f"[ProfileExtract] 后台任务异常 | qq_id={qq_id} | err={e}", exc_info=True)

            finally:
                # 释放 inflight
                state = self._states.get(qq_id)
                if state is not None:
                    state.inflight = False
                    # 后台任务结束后再 prune 一次，避免 state 长期堆积
                    try:
                        self._prune_states(now=time.time())
                    except Exception:
                        pass


_service: Optional[UserProfileExtractService] = None


def get_user_profile_extract_service() -> UserProfileExtractService:
    global _service
    if _service is None:
        _service = UserProfileExtractService()
    return _service
