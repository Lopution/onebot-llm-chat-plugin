"""Minimal CLI adapter for mika_chat_core."""

from __future__ import annotations

import argparse
import asyncio
import time
import uuid

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mika Chat CLI Adapter")
    parser.add_argument("--env-file", default="", help="指定 .env 文件路径")
    parser.add_argument("--user-id", default="cli_user", help="CLI 用户标识")
    parser.add_argument("--user-name", default="User", help="CLI 用户昵称")
    parser.add_argument("--session-id", default="", help="会话 ID（默认按 user-id 生成）")
    parser.add_argument("--platform", default="cli", help="平台标识（默认 cli）")
    return parser


def _build_private_envelope(
    *,
    session_id: str,
    platform: str,
    user_id: str,
    user_name: str,
    text: str,
) -> EventEnvelope:
    return EventEnvelope(
        schema_version=1,
        session_id=session_id,
        platform=platform,
        protocol="cli",
        message_id=uuid.uuid4().hex[:8],
        timestamp=time.time(),
        author=Author(id=user_id, nickname=user_name, role="user"),
        bot_self_id="mika_cli",
        content_parts=[ContentPart(kind="text", text=text)],
        meta={
            "intent": "private",
            "is_tome": True,
            "user_id": user_id,
        },
    )


async def _run(args: argparse.Namespace) -> int:
    from mika_chat_core.handlers import handle_private
    from mika_chat_core.mcp_client import McpToolClient, parse_mcp_server_configs
    from mika_chat_core.mika_api import MikaClient
    from mika_chat_core.runtime import (
        reset_runtime_state,
        set_client as set_runtime_client,
        set_config as set_runtime_config,
        set_message_port as set_runtime_message_port,
        set_platform_api_port as set_runtime_platform_api_port,
    )
    from mika_chat_core.tools_registry import get_tool_registry
    from mika_chat_core.tools_loader import ToolPluginManager
    from mika_chat_core.utils.prompt_loader import (
        get_character_name,
        get_system_prompt,
        load_error_messages,
    )
    from .cli_config import load_cli_config
    from .cli_ports import CliRuntimePorts

    config = load_cli_config(args.env_file or None)
    set_runtime_config(config)

    prompt_file = str(getattr(config, "mika_prompt_file", "system.yaml") or "system.yaml")
    system_prompt = get_system_prompt(prompt_file=prompt_file, master_name=config.mika_master_name)
    error_messages = load_error_messages(prompt_file)
    character_name = get_character_name(prompt_file)

    llm_cfg = config.get_llm_config()
    llm_keys = list(llm_cfg.get("api_keys") or [])
    primary_key = str(llm_keys[0] if llm_keys else config.llm_api_key)
    rotated_keys = llm_keys[1:] if len(llm_keys) > 1 else list(config.llm_api_key_list)

    client = MikaClient(
        api_key=primary_key,
        base_url=str(llm_cfg.get("base_url") or config.llm_base_url),
        model=str(llm_cfg.get("model") or config.llm_model),
        system_prompt=system_prompt,
        max_context=config.mika_max_context,
        api_key_list=rotated_keys,
        character_name=character_name,
        error_messages=error_messages if error_messages else None,
        enable_smart_search=True,
    )
    set_runtime_client(client)

    if bool(getattr(config, "mika_memory_enabled", False)):
        from mika_chat_core.utils.memory_store import get_memory_store

        await get_memory_store().init_table()
    if bool(getattr(config, "mika_knowledge_enabled", False)):
        from mika_chat_core.utils.knowledge_store import get_knowledge_store

        await get_knowledge_store().init_table()

    import mika_chat_core.tools as _builtin_tools  # noqa: F401

    tool_registry = get_tool_registry()
    mcp_client: McpToolClient | None = None
    plugin_manager: ToolPluginManager | None = None
    mcp_servers = parse_mcp_server_configs(getattr(config, "mika_mcp_servers", []))
    if mcp_servers:
        mcp_client = McpToolClient(registry=tool_registry)
        await mcp_client.connect_all(mcp_servers)

    plugin_manager = ToolPluginManager(registry=tool_registry)
    await plugin_manager.load(configured_plugins=list(getattr(config, "mika_tool_plugins", []) or []))

    for name, handler in tool_registry.get_all_handlers().items():
        client.register_tool_handler(name, handler)

    ports = CliRuntimePorts()
    set_runtime_message_port(ports)
    set_runtime_platform_api_port(ports)

    session_id = str(args.session_id or f"private:{args.user_id}")
    print("Mika CLI started. Type 'exit' or 'quit' to stop.")
    try:
        while True:
            raw = await asyncio.to_thread(input, "\n[You]: ")
            text = str(raw or "").strip()
            if not text:
                continue
            if text.lower() in {"exit", "quit"}:
                break

            envelope = _build_private_envelope(
                session_id=session_id,
                platform=str(args.platform or "cli"),
                user_id=str(args.user_id or "cli_user"),
                user_name=str(args.user_name or "User"),
                text=text,
            )
            await handle_private(envelope, plugin_config=config, mika_client=client)
    finally:
        if plugin_manager is not None:
            await plugin_manager.unload()
            tool_registry.clear_sources({"plugin"})
        if mcp_client is not None:
            await mcp_client.close()
            tool_registry.clear_sources({"mcp"})
        try:
            from mika_chat_core.planning.relevance_filter import close_relevance_filter
            from mika_chat_core.memory.retrieval_agent import close_memory_retrieval_agent

            await close_relevance_filter()
            await close_memory_retrieval_agent()
        except Exception:
            pass
        await client.close()
        reset_runtime_state()
    return 0


def main() -> None:
    args = _build_parser().parse_args()
    raise SystemExit(asyncio.run(_run(args)))
