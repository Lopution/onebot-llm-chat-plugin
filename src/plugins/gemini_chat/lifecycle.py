"""插件生命周期管理模块。

管理插件启动和关闭时的初始化与清理逻辑，包括：
- API 客户端初始化
- 上下文存储初始化（SQLite）
- 搜索引擎配置
- 用户档案存储初始化
- 图片缓存初始化
- API 连接验证

相关模块：
- [`gemini_api`](gemini_api.py:1): API 客户端
- [`config`](config.py:1): 插件配置定义
"""

from typing import TYPE_CHECKING, Optional
import httpx
from nonebot import get_driver

if TYPE_CHECKING:
    from nonebot.adapters import Bot

from .config import Config
from .gemini_api import GeminiClient
from .utils.search_engine import init_search_engine, close_search_engine, configure_search_cache, configure_classify_cache
from .utils.context_store import init_context_store, close_context_store
from .utils.user_profile import init_user_profile_store, get_user_profile_store
from .utils.prompt_loader import get_system_prompt, load_error_messages, get_character_name
from .utils.semantic_matcher import init_semantic_matcher
from .utils.recent_images import init_image_cache
from nonebot import logger as log
from .metrics import metrics


# ==================== Magic-number constants ====================
STARTUP_NOTIFY_MESSAGE = "Mika 上线啦~ ☆"
PROMPT_FILE_DEFAULT = "mika.yaml"
DATE_FORMAT_FALLBACK = "%Y年%m月%d日"

HEALTH_ENDPOINT_PATH = "/health"
METRICS_ENDPOINT_PATH = "/metrics"
PLUGIN_VERSION = "1.0.0"

IMAGE_CACHE_GAP_MULTIPLIER = 2
BASE_URL_RSTRIP_CHAR = "/"

API_VALIDATE_TIMEOUT_SECONDS = 10.0
API_VALIDATE_SUCCESS_STATUS = 200
API_VALIDATE_UNAUTHORIZED_STATUS = 401
API_VALIDATE_FORBIDDEN_STATUS = 403

# 获取驱动器
driver = get_driver()

# 全局 API 客户端实例
gemini_client: Optional[GeminiClient] = None

# 插件配置（将在初始化时设置）
plugin_config: Optional[Config] = None


def set_plugin_config(config: Config):
    """设置插件配置"""
    global plugin_config
    plugin_config = config


def get_gemini_client() -> GeminiClient:
    """获取 API 客户端实例"""
    return gemini_client


@driver.on_bot_connect
async def on_bot_connect(bot: "Bot"):
    """Bot 连接成功时触发"""
    log.success(f"Bot {bot.self_id} 已上线")
    
    # 可选：发送启动通知给管理员
    if plugin_config and plugin_config.gemini_master_id:
        from .utils.safe_api import safe_call_api

        await safe_call_api(
            bot,
            "send_private_msg",
            user_id=plugin_config.gemini_master_id,
            message=STARTUP_NOTIFY_MESSAGE,
        )


async def init_gemini():
    """启动时初始化 API 客户端"""
    global gemini_client
    
    # 初始化日志系统

    log.info("开始初始化 Gemini Chat 插件...")
    
    # 从 YAML 文件加载系统提示词（优先）或使用配置中的提示词
    prompt_file = getattr(plugin_config, 'gemini_prompt_file', PROMPT_FILE_DEFAULT)
    
    if prompt_file:
        # 使用外部 YAML 文件
        system_prompt = get_system_prompt(
            prompt_file=prompt_file,
            master_name=plugin_config.gemini_master_name
        )
        log.success(f"系统提示词已从 {prompt_file} 加载")
    else:
        # 回退到配置中的提示词
        from datetime import datetime
        current_date = datetime.now().strftime(DATE_FORMAT_FALLBACK)
        system_prompt = plugin_config.gemini_system_prompt.replace(
            "{master_name}",
            plugin_config.gemini_master_name
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
    
    gemini_client = GeminiClient(
        api_key=plugin_config.gemini_api_key,
        base_url=plugin_config.gemini_base_url,
        model=plugin_config.gemini_model,
        system_prompt=system_prompt,
        max_context=plugin_config.gemini_max_context,
        api_key_list=plugin_config.gemini_api_key_list,
        character_name=character_name,
        error_messages=error_messages if error_messages else None,
        enable_smart_search=True  # 启用智能搜索（LLM 意图识别 + 查询优化）
    )
    log.debug(f"API 客户端实例已创建 | model={plugin_config.gemini_model}")
    
    # 使用 TOOL_HANDLERS 批量注册工具处理器
    from .tools import TOOL_HANDLERS
    for name, handler in TOOL_HANDLERS.items():
        gemini_client.register_tool_handler(name, handler)
    log.debug(f"工具处理器已注册: {', '.join(TOOL_HANDLERS.keys())}")
    
    # 初始化上下文持久化存储
    await init_context_store()
    log.info("上下文持久化存储已初始化")
    
    # 初始化用户档案存储
    await init_user_profile_store()
    log.info("用户档案存储已初始化")
    
    # 初始化搜索引擎
    await init_search_engine()
    configure_search_cache(
        plugin_config.gemini_search_cache_ttl_seconds,
        plugin_config.gemini_search_cache_max_size,
    )
    configure_classify_cache(
        plugin_config.gemini_search_classify_cache_ttl_seconds,
        plugin_config.gemini_search_classify_cache_max_size,
    )
    log.info("搜索引擎已初始化")
    
    # 初始化图片缓存 (与上下文同步)
    # max_gap 设置为 max_context * 2，确保图片在文本记忆有效期内始终可用
    # 比如 100 轮上下文 = 200 条消息，那么图片在 200 条消息内都不会过期
    sync_gap = plugin_config.gemini_max_context * IMAGE_CACHE_GAP_MULTIPLIER
    init_image_cache(
        max_gap=sync_gap,
        require_keyword=plugin_config.gemini_image_require_keyword,
        max_images=plugin_config.gemini_max_images,
        max_entries=plugin_config.gemini_image_cache_max_entries,
        keywords=plugin_config.gemini_image_keywords or None,
    )
    log.info(f"图片缓存已初始化 | gap={sync_gap} | 无 TTL 限制")

    # 初始化图片处理器并设置并发限制
    from .utils.image_processor import get_image_processor
    get_image_processor(plugin_config.gemini_image_download_concurrency)
    
    # 初始化语义模型（后台加载）
    await init_semantic_matcher()
    
    # 启动时验证 API 连接（可通过配置禁用）
    if getattr(plugin_config, 'gemini_validate_on_startup', True):
        await validate_api_connection()
    
    # 注册健康检查端点（便于容器化部署）
    try:
        from nonebot import get_app
        from fastapi.responses import JSONResponse
        
        app = get_app()
        
        @app.get(HEALTH_ENDPOINT_PATH)
        async def health_check():
            """健康检查端点"""
            from .utils.context_store import get_db
            
            # 检查数据库连接
            try:
                db = await get_db()
                await db.execute("SELECT 1")
                db_status = "connected"
            except Exception:
                db_status = "disconnected"
            
            # 检查 API 客户端
            client_status = "ready" if gemini_client else "not_initialized"
            
            return JSONResponse({
                "status": "healthy",
                "database": db_status,
                "gemini_client": client_status,
                "plugin": "gemini_chat",
                "version": PLUGIN_VERSION
            })
        

        @app.get(METRICS_ENDPOINT_PATH)
        async def metrics_snapshot():
            return JSONResponse(metrics.snapshot())

        log.debug("健康检查端点已注册: /health")
    except Exception as e:
        log.warning(f"注册健康检查端点失败（可能不是 FastAPI 驱动）: {e}")
    
    log.success("Gemini Chat 插件初始化完成 ✅")


async def validate_api_connection():
    """验证 API 连接是否正常"""
    log.info("正在验证 API 连接...")
    
    # 获取有效的 API Keys
    api_keys = plugin_config.get_effective_api_keys() if hasattr(plugin_config, 'get_effective_api_keys') else [plugin_config.gemini_api_key]
    
    if not api_keys or not any(api_keys):
        log.error("❌ 未配置有效的 API Key")
        return
    
    base_url = plugin_config.gemini_base_url.rstrip(BASE_URL_RSTRIP_CHAR)
    log.debug(f"API Base URL: {base_url}")
    
    # 尝试每个 API Key
    for i, key in enumerate(api_keys):
        if not key:
            continue
        
        try:
            async with httpx.AsyncClient(timeout=API_VALIDATE_TIMEOUT_SECONDS) as client:
                # 发送一个简单的模型列表请求来验证连接
                response = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {key}"}
                )
                
                if response.status_code == API_VALIDATE_SUCCESS_STATUS:
                    log.success(f"✅ API Key #{i+1} 验证成功")
                    return  # 只要有一个成功就行
                elif response.status_code == API_VALIDATE_UNAUTHORIZED_STATUS:
                    log.warning(f"⚠️ API Key #{i+1} 认证失败（401）")
                elif response.status_code == API_VALIDATE_FORBIDDEN_STATUS:
                    log.warning(f"⚠️ API Key #{i+1} 权限不足（403）")
                elif response.status_code in (404, 405):
                    # 部分 OpenAI 兼容中转/网关未实现 /models，但仍可正常提供 /chat/completions
                    log.warning(f"⚠️ /models 不可用（{response.status_code}），改用 /chat/completions 进行验证")
                    try:
                        model_name = getattr(plugin_config, "gemini_fast_model", "") or plugin_config.gemini_model
                        ping_resp = await client.post(
                            f"{base_url}/chat/completions",
                            headers={
                                "Authorization": f"Bearer {key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": model_name,
                                "messages": [{"role": "user", "content": "ping"}],
                                # 尽量降低成本/延迟：只要能成功返回即可
                                "max_tokens": 1,
                                "temperature": 0,
                                "stream": False,
                            },
                        )
                        if ping_resp.status_code == API_VALIDATE_SUCCESS_STATUS:
                            log.success(f"✅ API Key #{i+1} 验证成功（/chat/completions）")
                            return
                        if ping_resp.status_code == API_VALIDATE_UNAUTHORIZED_STATUS:
                            log.warning(f"⚠️ API Key #{i+1} 认证失败（401, /chat/completions）")
                        elif ping_resp.status_code == API_VALIDATE_FORBIDDEN_STATUS:
                            log.warning(f"⚠️ API Key #{i+1} 权限不足（403, /chat/completions）")
                        else:
                            log.warning(
                                f"⚠️ API Key #{i+1} /chat/completions 返回状态码: {ping_resp.status_code}"
                            )
                    except httpx.TimeoutException:
                        log.warning(f"⚠️ API Key #{i+1} /chat/completions 连接超时")
                    except httpx.ConnectError as e:
                        log.warning(f"⚠️ API Key #{i+1} /chat/completions 连接失败: {str(e)}")
                    except Exception as e:
                        log.error(
                            f"⚠️ API Key #{i+1} /chat/completions 验证异常: {type(e).__name__}: {str(e)}",
                            exc_info=True,
                        )
                else:
                    log.warning(f"⚠️ API Key #{i+1} 返回状态码: {response.status_code}")
                    
        except httpx.TimeoutException:
            log.warning(f"⚠️ API Key #{i+1} 连接超时")
        except httpx.ConnectError as e:
            log.warning(f"⚠️ API Key #{i+1} 连接失败: {str(e)}")
        except Exception as e:
            log.error(f"⚠️ API Key #{i+1} 验证异常: {type(e).__name__}: {str(e)}", exc_info=True)
    
    log.error("❌ 所有 API Key 验证均失败，请检查配置")


async def close_gemini():
    """关闭时清理资源"""
    global gemini_client
    log.info("正在关闭 Gemini Chat 插件...")
    
    if gemini_client:
        await gemini_client.close()
        log.debug("API 客户端已关闭")

    # 关闭图片处理器（释放 httpx client）
    try:
        from .utils.image_processor import close_image_processor

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
    
    log.success("Gemini Chat 插件已安全关闭 ✅")
