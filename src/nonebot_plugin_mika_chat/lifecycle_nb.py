"""插件生命周期管理模块。

管理插件启动和关闭时的初始化与清理逻辑，包括：
- API 客户端初始化
- 上下文存储初始化（SQLite）
- 搜索引擎配置
- 用户档案存储初始化
- 图片缓存初始化
- API 连接验证

相关模块：
- [`mika_api`](mika_api.py:1): API 客户端
- [`config`](config.py:1): 插件配置定义
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import httpx
from nonebot import get_driver

from mika_chat_core.settings import Config
from mika_chat_core.core_service import create_core_service_router
from mika_chat_core.mika_api import MikaClient
from mika_chat_core.runtime import (
    get_client as get_runtime_client,
    get_config as get_runtime_config,
    set_client as set_runtime_client,
    set_config as set_runtime_config,
)
from mika_chat_core.utils.search_engine import (
    init_search_engine,
    close_search_engine,
    configure_search_cache,
    configure_classify_cache,
)
from mika_chat_core.llm.providers import build_provider_request
from mika_chat_core.utils.context_store import init_context_store, close_context_store
from mika_chat_core.utils.user_profile import init_user_profile_store, get_user_profile_store
from mika_chat_core.utils.prompt_loader import get_system_prompt, load_error_messages, get_character_name
from mika_chat_core.utils.semantic_matcher import init_semantic_matcher
from mika_chat_core.utils.recent_images import init_image_cache
from mika_chat_core.health_probe import (
    get_cached_api_probe as get_core_cached_api_probe,
    probe_api_health_once as probe_core_api_health_once,
)
from nonebot.adapters import Bot
from nonebot import logger as log
from mika_chat_core.metrics import metrics
from mika_chat_core.mcp_client import McpToolClient, parse_mcp_server_configs
from mika_chat_core.tools_registry import get_tool_registry
from mika_chat_core.tools_loader import ToolPluginManager
from mika_chat_core.utils.tool_state_store import apply_persisted_tool_states


# ==================== Magic-number constants ====================
STARTUP_NOTIFY_MESSAGE = "Mika 上线啦~ ☆"
PROMPT_FILE_DEFAULT = "mika.yaml"
DATE_FORMAT_FALLBACK = "%Y年%m月%d日"

HEALTH_ENDPOINT_PATH = "/health"
METRICS_ENDPOINT_PATH = "/metrics"
CORE_EVENTS_ENDPOINT_PATH = "/v1/events"
PLUGIN_VERSION = "1.0.0"

IMAGE_CACHE_GAP_MULTIPLIER = 2
BASE_URL_RSTRIP_CHAR = "/"

API_VALIDATE_TIMEOUT_SECONDS = 10.0
API_VALIDATE_SUCCESS_STATUS = 200
API_VALIDATE_UNAUTHORIZED_STATUS = 401
API_VALIDATE_FORBIDDEN_STATUS = 403
METRICS_PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# 获取驱动器
driver = get_driver()

@dataclass
class LifecycleRuntimeState:
    """生命周期运行态容器。

    说明：
    - 统一承载插件初始化后的运行态，避免在模块中散落多个裸全局变量。
    - 为后续依赖注入/多实例演进预留清晰边界。
    """

    config: Optional[Config] = None
    client: Optional[MikaClient] = None
    mcp_client: Optional[McpToolClient] = None
    plugin_manager: Optional[ToolPluginManager] = None


runtime_state = LifecycleRuntimeState()


def set_plugin_config(config: Config):
    """设置插件配置"""
    runtime_state.config = config
    set_runtime_config(config)


def get_plugin_config() -> Config:
    """获取插件配置（必须在初始化后使用）。"""
    if runtime_state.config is not None:
        return runtime_state.config
    return get_runtime_config()


def get_mika_client() -> MikaClient:
    """获取 API 客户端实例"""
    if runtime_state.client is not None:
        return runtime_state.client
    return get_runtime_client()


async def _probe_api_health_once(config: Config) -> Dict[str, Any]:
    """兼容包装：统一复用 core 层探测逻辑。"""
    return await probe_core_api_health_once(config)


async def _get_cached_api_probe(config: Config) -> Dict[str, Any]:
    """兼容包装：统一复用 core 层缓存探测逻辑。"""
    return await get_core_cached_api_probe(config)


@driver.on_bot_connect
async def on_bot_connect(bot: Bot):
    """Bot 连接成功时触发"""
    log.success(f"Bot {bot.self_id} 已上线")
    config = runtime_state.config or get_runtime_config()

    try:
        from .runtime_ports_nb import get_runtime_ports_bundle

        get_runtime_ports_bundle().platform_api.set_default_platform_bot(bot)
    except Exception as exc:
        log.warning(f"设置默认 PlatformApi bot 失败（已忽略）: {exc}")

    # 在适配层注册离线消息同步入口，避免核心模块直接依赖 NoneBot 事件装饰器。
    try:
        from mika_chat_core.handlers import sync_offline_messages

        await sync_offline_messages()
    except Exception as exc:
        log.warning(f"触发离线消息同步失败（已忽略）: {exc}")
    
    # 可选：发送启动通知给管理员
    master_user_id = str(getattr(config, "mika_master_id", "") or "").strip() if config else ""
    if master_user_id:
        from .safe_api import safe_call_api

        user_id_arg = int(master_user_id) if master_user_id.isdigit() else master_user_id
        await safe_call_api(
            bot,
            "send_private_msg",
            user_id=user_id_arg,
            message=STARTUP_NOTIFY_MESSAGE,
        )


async def init_mika():
    """启动时初始化 API 客户端"""
    config = get_plugin_config()
    
    # 初始化日志系统

    log.info("开始初始化 Mika Chat 插件...")
    
    # 从 YAML 文件加载系统提示词（优先）或使用配置中的提示词
    prompt_file = getattr(config, 'mika_prompt_file', PROMPT_FILE_DEFAULT)

    try:
        from mika_chat_core.persona.persona_manager import get_persona_manager

        await get_persona_manager().init_table(seed_prompt_file=prompt_file or "system.yaml")
        log.info("Persona 存储已初始化")
    except Exception as exc:
        log.warning(f"Persona 存储初始化失败，回退文件提示词: {exc}")
    
    if prompt_file:
        # 使用外部 YAML 文件
        system_prompt = get_system_prompt(
            prompt_file=prompt_file,
            master_name=config.mika_master_name
        )
        log.success(f"系统提示词已从 {prompt_file} 加载")
    else:
        # 回退到配置中的提示词
        from datetime import datetime
        current_date = datetime.now().strftime(DATE_FORMAT_FALLBACK)
        system_prompt = config.mika_system_prompt.replace(
            "{master_name}",
            config.mika_master_name
        ).replace(
            "{current_date}",
            current_date
        )
        log.info("使用配置中的系统提示词")
    
    # 加载错误消息和角色名称
    error_messages = load_error_messages(prompt_file)
    character_name = get_character_name(prompt_file)
    
    if error_messages:
        log.debug(f"已加载 {len(error_messages)} 条自定义错误消息")
    
    llm_cfg = config.get_llm_config()
    llm_keys = list(llm_cfg.get("api_keys") or [])
    primary_key = str(llm_keys[0] if llm_keys else config.llm_api_key)
    rotated_keys = llm_keys[1:] if len(llm_keys) > 1 else list(config.llm_api_key_list)
    runtime_state.client = MikaClient(
        api_key=primary_key,
        base_url=str(llm_cfg.get("base_url") or config.llm_base_url),
        model=str(llm_cfg.get("model") or config.llm_model),
        system_prompt=system_prompt,
        max_context=config.mika_max_context,
        api_key_list=rotated_keys,
        character_name=character_name,
        error_messages=error_messages if error_messages else None,
        enable_smart_search=True  # 启用智能搜索（LLM 意图识别 + 查询优化）
    )
    set_runtime_client(runtime_state.client)
    log.debug(
        f"API 客户端实例已创建 | model={llm_cfg.get('model') or config.llm_model} | "
        f"provider={llm_cfg.get('provider')}"
    )
    core_runtime_cfg = config.get_core_runtime_config()
    log.info(f"Core Runtime 模式: remote | remote={core_runtime_cfg['remote_base_url']}")
    
    # 注册内置/动态工具处理器（包含 MCP）
    import mika_chat_core.tools as _builtin_tools  # noqa: F401

    tool_registry = get_tool_registry()
    mcp_servers = parse_mcp_server_configs(getattr(config, "mika_mcp_servers", []))
    runtime_state.mcp_client = None
    if mcp_servers:
        runtime_state.mcp_client = McpToolClient(registry=tool_registry)
        registered_count = await runtime_state.mcp_client.connect_all(mcp_servers)
        log.info(
            f"MCP 工具初始化完成 | servers={len(mcp_servers)} | tools={registered_count}"
        )

    runtime_state.plugin_manager = ToolPluginManager(registry=tool_registry)
    configured_plugins = list(getattr(config, "mika_tool_plugins", []) or [])
    loaded_plugins = await runtime_state.plugin_manager.load(configured_plugins=configured_plugins)
    if loaded_plugins > 0:
        log.info(f"工具插件初始化完成 | plugins={loaded_plugins}")
    elif configured_plugins:
        log.warning("工具插件配置存在但未加载到可用插件")

    await apply_persisted_tool_states(tool_registry)

    effective_handlers = tool_registry.get_all_handlers()
    for name, handler in effective_handlers.items():
        runtime_state.client.register_tool_handler(name, handler)
    log.debug(f"工具处理器已注册: {', '.join(sorted(effective_handlers.keys()))}")
    
    # 初始化上下文持久化存储
    await init_context_store()
    log.info("上下文持久化存储已初始化")

    if bool(getattr(config, "mika_memory_enabled", False)):
        from mika_chat_core.utils.memory_store import get_memory_store

        memory_store = get_memory_store()
        await memory_store.init_table()
        log.info("长期记忆存储已初始化")

    if bool(getattr(config, "mika_knowledge_enabled", False)):
        from mika_chat_core.utils.knowledge_store import get_knowledge_store

        knowledge_store = get_knowledge_store()
        await knowledge_store.init_table()
        log.info("知识库存储已初始化")
    
    # 初始化用户档案存储
    await init_user_profile_store()
    log.info("用户档案存储已初始化")
    
    # 初始化搜索引擎
    await init_search_engine()
    search_cfg = config.get_search_config()
    configure_search_cache(
        int(search_cfg["cache_ttl_seconds"]),
        int(search_cfg["cache_max_size"]),
    )
    configure_classify_cache(
        int(search_cfg["classify_cache_ttl_seconds"]),
        int(search_cfg["classify_cache_max_size"]),
    )
    log.info("搜索引擎已初始化")
    
    # 初始化图片缓存 (与上下文同步)
    # max_gap 设置为 max_context * 2，确保图片在文本记忆有效期内始终可用
    # 比如 100 轮上下文 = 200 条消息，那么图片在 200 条消息内都不会过期
    image_cfg = config.get_image_config()
    sync_gap = config.mika_max_context * IMAGE_CACHE_GAP_MULTIPLIER
    init_image_cache(
        max_gap=sync_gap,
        require_keyword=bool(image_cfg["require_keyword"]),
        max_images=int(image_cfg["max_images"]),
        max_entries=int(image_cfg["cache_max_entries"]),
        keywords=image_cfg["keywords"] or None,
    )
    log.info(f"图片缓存已初始化 | gap={sync_gap} | 无 TTL 限制")

    # 初始化图片处理器并设置并发限制
    from mika_chat_core.utils.image_processor import get_image_processor
    get_image_processor(int(image_cfg["download_concurrency"]))
    
    # 初始化语义模型（后台加载）
    await init_semantic_matcher()
    
    # 启动时验证 API 连接（可通过配置禁用）
    if getattr(config, 'mika_validate_on_startup', True):
        await validate_api_connection()
    
    # 注册健康检查端点（便于容器化部署）
    try:
        from nonebot import get_app
        from fastapi import Request
        from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
        
        app = get_app()
        observability_cfg = config.get_observability_config()
        
        @app.get(HEALTH_ENDPOINT_PATH)
        async def health_check():
            """健康检查端点"""
            from mika_chat_core.utils.context_store import get_db
            
            # 检查数据库连接
            try:
                db = await get_db()
                await db.execute("SELECT 1")
                db_status = "connected"
            except Exception:
                db_status = "disconnected"
            
            # 检查 API 客户端
            client_status = "ready" if runtime_state.client else "not_initialized"
            probe_result = await _get_cached_api_probe(config)
            overall_status = "healthy"
            if db_status != "connected" or client_status != "ready":
                overall_status = "degraded"
            if (
                bool(observability_cfg["health_api_probe_enabled"])
                and probe_result.get("status") != "healthy"
            ):
                overall_status = "degraded"
            
            return JSONResponse({
                "status": overall_status,
                "database": db_status,
                "mika_client": client_status,
                "api_probe": probe_result,
                "plugin": "mika_chat",
                "version": PLUGIN_VERSION
            })
        

        @app.get(METRICS_ENDPOINT_PATH)
        async def metrics_snapshot(request: Request):
            accept = (request.headers.get("accept") or "").lower()
            fmt = (request.query_params.get("format") or "").strip().lower()
            wants_prometheus = fmt in {"prometheus", "prom"} or ("text/plain" in accept) or (
                "application/openmetrics-text" in accept
            )
            if wants_prometheus and bool(observability_cfg["prometheus_enabled"]):
                return PlainTextResponse(
                    metrics.to_prometheus(plugin_version=PLUGIN_VERSION),
                    media_type=METRICS_PROMETHEUS_CONTENT_TYPE,
                )
            return JSONResponse(metrics.snapshot())

        @app.get(f"{METRICS_ENDPOINT_PATH}/prometheus")
        async def metrics_prometheus():
            if not bool(observability_cfg["prometheus_enabled"]):
                return JSONResponse({"error": "prometheus export disabled"}, status_code=404)
            return PlainTextResponse(
                metrics.to_prometheus(plugin_version=PLUGIN_VERSION),
                media_type=METRICS_PROMETHEUS_CONTENT_TYPE,
            )

        existing_core_route = any(
            getattr(route, "path", "") == CORE_EVENTS_ENDPOINT_PATH
            and "POST" in (getattr(route, "methods", set()) or set())
            for route in app.routes
        )
        if not existing_core_route:
            app.include_router(create_core_service_router())
            log.debug(f"Core Service 端点已注册: {CORE_EVENTS_ENDPOINT_PATH}")

        if bool(getattr(config, "mika_webui_enabled", False)):
            from mika_chat_core.webui import create_webui_router, normalize_base_path

            webui_base_path = normalize_base_path(
                str(getattr(config, "mika_webui_base_path", "/webui") or "/webui")
            )
            webui_api_health_path = f"{webui_base_path}/api/dashboard/health"
            existing_webui_route = any(
                getattr(route, "path", "") == webui_api_health_path for route in app.routes
            )
            if not existing_webui_route:
                app.include_router(
                    create_webui_router(
                        settings_getter=get_plugin_config,
                        base_path=webui_base_path,
                    )
                )
                log.debug(f"WebUI API 端点已注册: {webui_base_path}/api")

            static_dir = (
                Path(__file__).resolve().parent.parent
                / "mika_chat_core"
                / "webui"
                / "static"
            )
            index_file = static_dir / "index.html"
            static_root = static_dir.resolve()
            if index_file.is_file():
                fallback_path = f"{webui_base_path}/{{path:path}}"
                root_path = webui_base_path

                if not any(getattr(route, "path", "") == root_path for route in app.routes):
                    async def _webui_index() -> FileResponse:
                        return FileResponse(index_file)

                    app.add_api_route(
                        root_path,
                        _webui_index,
                        methods=["GET"],
                        include_in_schema=False,
                    )

                if not any(getattr(route, "path", "") == fallback_path for route in app.routes):
                    async def _webui_spa(path: str) -> FileResponse:
                        target = (static_dir / path).resolve()
                        if target.is_file() and target.is_relative_to(static_root):
                            return FileResponse(target)
                        return FileResponse(index_file)

                    app.add_api_route(
                        fallback_path,
                        _webui_spa,
                        methods=["GET"],
                        include_in_schema=False,
                    )
                log.debug(f"WebUI 静态页面已注册: {webui_base_path}/")
            else:
                log.info("WebUI 已启用但未找到前端构建产物，跳过静态页面托管")

        log.debug("健康检查端点已注册: /health")
        log.debug("指标端点已注册: /metrics, /metrics/prometheus")
    except Exception as e:
        log.warning(f"注册健康检查端点失败（可能不是 FastAPI 驱动）: {e}")
    
    log.success("Mika Chat 插件初始化完成 ✅")


async def validate_api_connection():
    """验证 API 连接是否正常"""
    log.info("正在验证 API 连接...")
    config = get_plugin_config()

    llm_cfg = config.get_llm_config()
    api_keys = list(llm_cfg.get("api_keys") or [])

    if not api_keys or not any(api_keys):
        log.error("❌ 未配置有效的 API Key")
        return

    base_url = str(llm_cfg.get("base_url") or config.llm_base_url).rstrip(BASE_URL_RSTRIP_CHAR)
    provider_name = str(llm_cfg.get("provider") or "openai_compat")
    model_name = str(llm_cfg.get("fast_model") or llm_cfg.get("model") or config.llm_model)
    extra_headers = dict(llm_cfg.get("extra_headers") or {})
    log.debug(f"API Base URL: {base_url} | provider={provider_name}")

    # 尝试每个 API Key
    for i, key in enumerate(api_keys):
        if not key:
            continue

        try:
            async with httpx.AsyncClient(timeout=API_VALIDATE_TIMEOUT_SECONDS) as client:
                prepared = build_provider_request(
                    provider=provider_name,
                    base_url=base_url,
                    model=model_name,
                    api_key=key,
                    request_body={
                        "model": model_name,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                        "temperature": 0,
                        "stream": False,
                    },
                    extra_headers=extra_headers,
                    default_temperature=0.0,
                )
                response = await client.post(
                    prepared.url,
                    headers=prepared.headers,
                    params=prepared.params,
                    json=prepared.json_body,
                )

                if response.status_code == API_VALIDATE_SUCCESS_STATUS:
                    log.success(f"✅ API Key #{i+1} 验证成功（provider={provider_name}）")
                    return  # 只要有一个成功就行
                elif response.status_code == API_VALIDATE_UNAUTHORIZED_STATUS:
                    log.warning(f"⚠️ API Key #{i+1} 认证失败（401）")
                elif response.status_code == API_VALIDATE_FORBIDDEN_STATUS:
                    log.warning(f"⚠️ API Key #{i+1} 权限不足（403）")
                else:
                    log.warning(f"⚠️ API Key #{i+1} 返回状态码: {response.status_code}（provider={provider_name}）")

        except httpx.TimeoutException:
            log.warning(f"⚠️ API Key #{i+1} 连接超时")
        except httpx.ConnectError as e:
            log.warning(f"⚠️ API Key #{i+1} 连接失败: {str(e)}")
        except Exception as e:
            log.error(f"⚠️ API Key #{i+1} 验证异常: {type(e).__name__}: {str(e)}", exc_info=True)
    
    log.error("❌ 所有 API Key 验证均失败，请检查配置")


async def close_mika():
    """关闭时清理资源"""
    log.info("正在关闭 Mika Chat 插件...")
    
    if runtime_state.client:
        await runtime_state.client.close()
        runtime_state.client = None
        set_runtime_client(None)
        log.debug("API 客户端已关闭")

    if runtime_state.plugin_manager is not None:
        try:
            unloaded = await runtime_state.plugin_manager.unload()
            log.debug(f"工具插件已卸载 | plugins={unloaded}")
        finally:
            runtime_state.plugin_manager = None
            removed = get_tool_registry().clear_sources({"plugin"})
            if removed:
                log.debug(f"清理残留插件工具 | removed_tools={removed}")

    if runtime_state.mcp_client is not None:
        try:
            await runtime_state.mcp_client.close()
        finally:
            runtime_state.mcp_client = None
            removed = get_tool_registry().clear_sources({"mcp"})
            log.debug(f"MCP 客户端已关闭 | removed_tools={removed}")

    # 关闭图片处理器（释放 httpx client）
    try:
        from mika_chat_core.utils.image_processor import close_image_processor

        await close_image_processor()
        log.debug("图片处理器已关闭")
    except Exception as e:
        log.debug(f"关闭图片处理器失败(忽略): {e}")
    
    # 关闭上下文持久化存储
    await close_context_store()
    log.debug("上下文存储已关闭")
    
    # 关闭搜索引擎 HTTP 客户端
    await close_search_engine()
    log.debug("搜索引擎已关闭")

    # 关闭共享 LLM 辅助客户端（相关性过滤 / 记忆检索）
    try:
        from mika_chat_core.planning.relevance_filter import close_relevance_filter
        from mika_chat_core.memory.retrieval_agent import close_memory_retrieval_agent

        await close_relevance_filter()
        await close_memory_retrieval_agent()
        log.debug("共享 LLM 辅助客户端已关闭")
    except Exception as e:
        log.debug(f"关闭共享 LLM 辅助客户端失败(忽略): {e}")
    
    log.success("Mika Chat 插件已安全关闭 ✅")
