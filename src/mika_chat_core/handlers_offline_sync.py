"""Handlers - 离线消息同步流程。"""

from __future__ import annotations

from typing import Any, Awaitable, Callable


async def sync_offline_messages_task_flow(
    *,
    get_config_fn: Callable[[], Any],
    get_mika_client_fn: Callable[[], Any],
    get_runtime_platform_api_port_fn: Callable[[], Any],
    sleep_fn: Callable[[float], Awaitable[None]],
    log_obj: Any,
) -> None:
    """同步离线消息的具体逻辑。"""
    plugin_config = get_config_fn()

    if not bool(getattr(plugin_config, "mika_offline_sync_enabled", False)):
        log_obj.info("离线消息同步已关闭，跳过")
        return

    if not plugin_config.mika_group_whitelist:
        log_obj.info("未配置白名单群组，跳过离线消息同步")
        return

    await sleep_fn(5)

    log_obj.info("开始同步离线消息 (后台任务)...")
    mika_client = get_mika_client_fn()

    if not mika_client.is_persistent:
        log_obj.warning("未启用持久化存储，跳过离线消息同步")
        return

    platform_api_port = get_runtime_platform_api_port_fn()
    if platform_api_port is None:
        log_obj.warning("离线消息同步跳过：PlatformApiPort 未注册")
        return

    try:
        caps = platform_api_port.capabilities()
    except Exception:
        caps = None
    if caps is not None and not bool(getattr(caps, "supports_history_fetch", False)):
        log_obj.warning("离线消息同步跳过：当前适配器未声明 supports_history_fetch")
        return

    for group_id in list(plugin_config.mika_group_whitelist):
        try:
            existing_context = await mika_client.get_context(user_id="_sync_", group_id=str(group_id))
            existing_ids = set()
            for msg in existing_context:
                if "message_id" in msg:
                    existing_ids.add(str(msg["message_id"]))

            history_limit = int(plugin_config.mika_history_count)
            try:
                messages: Any = await platform_api_port.fetch_conversation_history(
                    conversation_id=str(group_id),
                    limit=history_limit,
                )
            except Exception as exc:
                log_obj.warning(f"群 {group_id} 离线同步：PlatformApiPort 拉取历史失败 | error={exc}")
                continue
            if messages is None:
                log_obj.warning(f"群 {group_id} 离线同步跳过：平台未返回历史记录")
                continue

            if not isinstance(messages, list):
                log_obj.warning(
                    f"群 {group_id} 离线同步跳过：platform history 返回类型异常 type={type(messages).__name__}"
                )
                continue

            if not messages:
                continue

            new_messages_count = 0
            messages.sort(key=lambda item: item.get("time", 0))

            for msg in messages:
                msg_id = str(msg.get("message_id", ""))
                if not msg_id or msg_id in existing_ids:
                    continue

                user_id = str(msg.get("user_id"))
                raw_message = msg.get("raw_message", "") or msg.get("message", "")
                if not raw_message:
                    continue

                nickname = msg.get("sender", {}).get("card", "") or msg.get("sender", {}).get("nickname", "")
                tag = f"{nickname}({user_id})"
                formatted_message = f"[{tag}]: {raw_message}"
                msg_time = msg.get("time")

                await mika_client.add_message(
                    user_id=user_id,
                    role="user",
                    content=formatted_message,
                    group_id=str(group_id),
                    message_id=msg_id,
                    timestamp=msg_time,
                )
                new_messages_count += 1

            if new_messages_count > 0:
                log_obj.success(f"群 {group_id} 离线消息同步完成 | 新增 {new_messages_count} 条")
            else:
                log_obj.debug(f"群 {group_id} 无需同步 (最新)")

        except Exception as exc:
            log_obj.warning(f"同步群 {group_id} 消息失败: {exc}")
