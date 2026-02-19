"""pytest 配置和共享 fixtures。

修复目标：
1) 避免把 `src/plugins` 置顶导致第三方同名包被遮蔽。
2) 在缺少外部依赖（httpx/pydantic/nonebot 等）时，仅对 tests 注入最小 stub。
3) 避免与 pytest-cov 的 --cov* 选项注册冲突。
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STUBS_ROOT = Path(__file__).resolve().parent / "stubs"


def _load_stub_package(package: str, package_dir: Path) -> None:
    """从 tests/stubs 以“包”的形式加载模块，并注入到 sys.modules。

    这样无需修改 sys.path，也能支持 `import nonebot.adapters...` 这类子包导入。
    """

    init_py = package_dir / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        package,
        init_py,
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load stub package: {package} from {init_py}")

    module = importlib.util.module_from_spec(spec)
    # 先注册，避免 stub 包内部再 import 自己的子模块时出现递归问题
    sys.modules[package] = module
    spec.loader.exec_module(module)


def _ensure_dependency_or_stub(package: str, *, force_stub: bool = False) -> None:
    if not force_stub and importlib.util.find_spec(package) is not None:
        return
    stub_dir = STUBS_ROOT / package
    _load_stub_package(package, stub_dir)


# ==================== tests-only 依赖注入（仅当真实依赖缺失时启用） ====================
_ensure_dependency_or_stub("pydantic")
_ensure_dependency_or_stub("httpx")
_ensure_dependency_or_stub("nonebot")
_ensure_dependency_or_stub("nonebot_plugin_localstore")
# 受限沙箱环境里真实 aiosqlite 可能卡死（后台线程无法唤醒事件循环），默认强制使用 stub。
# 如需在本机/CI 使用真实 aiosqlite 以覆盖更接近生产的行为，可设置：MIKA_TEST_USE_REAL_AIOSQLITE=1
_use_real_aiosqlite = os.getenv("MIKA_TEST_USE_REAL_AIOSQLITE") == "1"
_ensure_dependency_or_stub("aiosqlite", force_stub=not _use_real_aiosqlite)


# ==================== 测试导入路径设置 ====================
# 允许 `import mika_chat_core`（tests 中大量使用）。
src_dir = PROJECT_ROOT / "src"
src_dir_str = str(src_dir)
if src_dir_str not in sys.path:
    sys.path.append(src_dir_str)


def pytest_addoption(parser):
    """兼容评测/精简环境：允许 pyproject.toml 的 --cov / --cov-report 参数存在。

    该仓库的 pytest 配置里可能包含 pytest-cov 的 addopts；
    但评测环境不一定预装 pytest-cov。
    这里注册同名参数用于“无覆盖率运行”，避免命令行解析阶段直接失败。
    """

    # 若已安装 pytest-cov，则其会自己注册 --cov*，这里不要重复注册以免冲突。
    if importlib.util.find_spec("pytest_cov") is not None:
        return

    # pytest-cov 常用选项（只注册，不实际产出覆盖率报告）
    parser.addoption("--cov", action="append", default=[])
    parser.addoption("--cov-report", action="append", default=[])
    parser.addoption("--cov-branch", action="store_true", default=False)

# ==================== 在导入插件模块前 Mock NoneBot ====================
# 必须在 import mika_chat_core 之前 mock，否则 __init__.py 会调用 get_plugin_config() 报错
#
# 关键修复：将 patch 从 pytest fixture 改为模块级别立即执行
# 原因：测试模块在收集阶段（import 时）就触发了 mika_chat_core 模块导入，
#       此时 pytest fixture 尚未生效，导致 get_plugin_config() 调用失败。
# 解决方案：在 conftest.py 文件头部直接使用 patch().start()，确保在任何模块导入前就生效。

_mock_driver = MagicMock()
_mock_driver.config = MagicMock()
_mock_driver.config.command_start = {"/"}
_mock_driver.config.command_sep = {"."}

def _fake_get_plugin_config(model: object):
    """为 tests 提供稳定的插件配置。

    - 若真实 pydantic/Config 可用：直接实例化传入的 model（通常是 mika_chat_core.config.Config）
      这样新增字段会自动带默认值，避免 MagicMock 缺字段导致 AttributeError。
    - 若 model 无法实例化（极简环境 / stub 不兼容）：回退到最小 MagicMock。
    """

    try:
        if callable(model):
            return model(
                llm_api_key="test-api-key-12345678901234567890",
                llm_api_key_list=[],
                llm_base_url="https://test.api.example.com/v1",
                llm_model="mika-test",
                mika_validate_on_startup=False,
                mika_master_id=123456789,
                mika_master_name="TestSensei",
                mika_prompt_file="",
                mika_system_prompt="测试助手",
                mika_max_context=40,
                mika_history_count=50,
                mika_reply_private=True,
                mika_reply_at=True,
                mika_max_images=10,
                mika_forward_threshold=300,
                mika_group_whitelist=[],
            )
    except Exception:
        pass

    # 兜底：极简 MagicMock（尽量覆盖常用字段）
    fallback = MagicMock()
    fallback.llm_api_key = "test-api-key-12345678901234567890"
    fallback.llm_api_key_list = []
    fallback.llm_base_url = "https://test.api.example.com/v1"
    fallback.llm_model = "mika-test"
    fallback.mika_validate_on_startup = False
    fallback.mika_master_id = 123456789
    fallback.mika_master_name = "TestSensei"
    fallback.mika_prompt_file = ""
    fallback.mika_system_prompt = "测试助手"
    fallback.mika_max_context = 40
    fallback.mika_history_count = 50
    fallback.mika_reply_private = True
    fallback.mika_reply_at = True
    fallback.mika_max_images = 10
    fallback.mika_forward_threshold = 300
    fallback.mika_group_whitelist = []
    return fallback

# 设置 nonebot 内部的 _driver 变量，让 get_driver() 成功
import nonebot

nonebot._driver = _mock_driver

# ==================== 模块级别 Patch（立即生效） ====================
# 直接使用 patch().start()，确保在任何测试模块导入前就生效
# 这些 patch 会在整个测试进程期间保持活跃

_driver_patcher = patch("nonebot.get_driver", return_value=_mock_driver)
_config_patcher = patch("nonebot.get_plugin_config", side_effect=_fake_get_plugin_config)

# 立即启动 patch，在模块导入时就生效
_driver_patcher.start()
_config_patcher.start()

# 注册 atexit 清理函数，确保进程退出时正确停止 patch
import atexit

def _cleanup_patches():
    """清理模块级别的 patch。"""
    try:
        _config_patcher.stop()
    except RuntimeError:
        pass
    try:
        _driver_patcher.stop()
    except RuntimeError:
        pass

atexit.register(_cleanup_patches)


@pytest.fixture(autouse=True)
def reset_runtime_state_between_tests():
    """清理 runtime 全局状态，避免测试间环境污染。"""
    from mika_chat_core.config import Config
    from mika_chat_core import runtime as runtime_module
    from mika_chat_core.tools_registry import get_tool_registry

    runtime_module.reset_runtime_state()
    runtime_module.set_config(
        Config(
            llm_api_key="test-api-key-12345678901234567890",
            llm_api_key_list=[],
            llm_base_url="https://test.api.example.com/v1",
            llm_model="mika-test",
            llm_fast_model="mika-test-fast",
            mika_validate_on_startup=False,
            mika_master_id=123456789,
            mika_master_name="TestSensei",
            mika_prompt_file="",
            mika_system_prompt="测试助手",
            mika_max_context=40,
            mika_history_count=50,
            mika_reply_private=True,
            mika_reply_at=True,
            mika_max_images=10,
            mika_forward_threshold=300,
            mika_group_whitelist=[],
        )
    )
    get_tool_registry().clear_sources({"mcp", "plugin"})
    yield
    get_tool_registry().clear_sources({"mcp", "plugin"})
    runtime_module.reset_runtime_state()


# ==================== pytest-asyncio 配置 ====================
# 注意：不再需要自定义 event_loop fixture
# pytest-asyncio 0.21+ 已废弃此方式，应使用 pyproject.toml 中的 asyncio_mode = "auto"
# 该配置已在 [tool.pytest.ini_options] 中设置


# ==================== 临时数据库 Fixture ====================

@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """创建临时数据库路径"""
    db_path = tmp_path / "test_contexts.db"
    return db_path


@pytest.fixture
async def temp_database(temp_db_path: Path):
    """
    创建临时 SQLite 数据库用于测试
    
    测试结束后自动清理数据库文件
    """
    import aiosqlite
    
    # 确保目录存在
    temp_db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 创建并初始化数据库
    conn = await aiosqlite.connect(str(temp_db_path))
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            context_key TEXT NOT NULL UNIQUE,
            messages TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_context_key ON contexts(context_key)
    """)

    # 创建 message_archive 表用于测试
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS message_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            context_key TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            message_id TEXT,
            timestamp REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_archive_key_time ON message_archive(context_key, timestamp)
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS context_summaries (
            context_key TEXT PRIMARY KEY,
            summary TEXT NOT NULL DEFAULT '',
            source_message_count INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await conn.commit()
    
    yield conn
    
    # 清理
    await conn.close()
    if temp_db_path.exists():
        temp_db_path.unlink()


# ==================== Mock API 客户端 Fixture ====================

@pytest.fixture
def mock_httpx_client():
    """
    创建 Mock httpx 客户端
    
    模拟 API 响应，避免真实网络调用
    """
    mock_client = AsyncMock()
    mock_client.is_closed = False
    
    # 默认成功响应
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "content": "这是模拟的 AI 回复"
            }
        }]
    }
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {}
    mock_response.text = ""
    
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.aclose = AsyncMock()
    
    return mock_client


@pytest.fixture
def mock_api_response_success():
    """成功的 API 响应数据"""
    return {
        "choices": [{
            "message": {
                "content": "你好！我是测试助手，很高兴见到你~"
            }
        }]
    }


@pytest.fixture
def mock_api_response_empty():
    """空回复的 API 响应数据"""
    return {
        "choices": [{
            "message": {
                "content": ""
            }
        }]
    }


@pytest.fixture
def mock_api_response_error():
    """错误的 API 响应"""
    return {
        "error": {
            "message": "Rate limit exceeded",
            "type": "rate_limit_error"
        }
    }


# ==================== 测试配置 Fixture ====================

@pytest.fixture
def test_config_dict():
    """测试用配置字典"""
    return {
        "llm_api_key": "test-api-key-1234567890abcdef12345678",
        "llm_api_key_list": [],
        "llm_base_url": "https://test.api.example.com/v1",
        "llm_model": "mika-test-model",
        "mika_validate_on_startup": False,
        "mika_master_id": 123456789,
        "mika_master_name": "TestMaster",
        "mika_prompt_file": "",
        "mika_system_prompt": "你是一个测试助手",
        "mika_max_context": 10,
        "mika_history_count": 20,
        "mika_reply_private": True,
        "mika_reply_at": True,
        "mika_max_images": 5,
        "mika_forward_threshold": 200,
        "mika_group_whitelist": [111222333, 444555666],
    }


@pytest.fixture
def valid_api_key():
    """有效的 API Key（测试用）"""
    return "AIzaSyTest1234567890abcdefghij"


@pytest.fixture
def invalid_api_key_short():
    """过短的无效 API Key"""
    return "short"


@pytest.fixture
def invalid_api_key_with_space():
    """包含空格的无效 API Key"""
    return "AIzaSyTest 1234567890abcdefghij"


# ==================== Mock NoneBot 环境 Fixture ====================

@pytest.fixture
def mock_nonebot_env():
    """
    Mock NoneBot 环境
    
    用于测试依赖 NoneBot 的模块
    """
    with patch("nonebot.get_driver") as mock_driver, \
         patch("nonebot.get_plugin_config") as mock_config, \
         patch("nonebot.get_bot") as mock_bot:
        
        # Mock driver
        driver_instance = MagicMock()
        mock_driver.return_value = driver_instance
        
        # Mock config
        mock_config.return_value = MagicMock(
            llm_api_key="test-key-12345678901234567890",
            mika_master_id=123456789,
            mika_master_name="TestSensei"
        )
        
        # Mock bot
        bot_instance = AsyncMock()
        bot_instance.self_id = "987654321"
        mock_bot.return_value = bot_instance
        
        yield {
            "driver": mock_driver,
            "config": mock_config,
            "bot": mock_bot,
            "driver_instance": driver_instance,
            "bot_instance": bot_instance
        }


# ==================== Mock Message Fixture ====================

@pytest.fixture
def mock_message_with_text():
    """创建带文本的 Mock 消息"""
    mock_msg = MagicMock()
    mock_segment = MagicMock()
    mock_segment.type = "text"
    mock_segment.data = {"text": "测试消息内容"}
    mock_msg.__iter__ = lambda self: iter([mock_segment])
    return mock_msg


@pytest.fixture
def mock_message_with_image():
    """创建带图片的 Mock 消息"""
    mock_msg = MagicMock()
    
    text_segment = MagicMock()
    text_segment.type = "text"
    text_segment.data = {"text": "看这张图片"}
    
    image_segment = MagicMock()
    image_segment.type = "image"
    image_segment.data = {"url": "https://example.com/image.jpg"}
    
    mock_msg.__iter__ = lambda self: iter([text_segment, image_segment])
    return mock_msg


@pytest.fixture
def mock_message_with_gif():
    """创建带 GIF 的 Mock 消息"""
    mock_msg = MagicMock()
    
    image_segment = MagicMock()
    image_segment.type = "image"
    image_segment.data = {"url": "https://example.com/animation.gif"}
    
    mock_msg.__iter__ = lambda self: iter([image_segment])
    return mock_msg


@pytest.fixture
def mock_message_with_multiple_images():
    """创建带多张图片的 Mock 消息"""
    mock_msg = MagicMock()
    
    segments = []
    for i in range(5):
        seg = MagicMock()
        seg.type = "image"
        seg.data = {"url": f"https://example.com/image{i}.jpg"}
        segments.append(seg)
    
    mock_msg.__iter__ = lambda self: iter(segments)
    return mock_msg


# ==================== 临时提示词文件 Fixture ====================

@pytest.fixture
def temp_prompts_dir(tmp_path: Path) -> Path:
    """创建临时提示词目录"""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    return prompts_dir


@pytest.fixture
def sample_prompt_yaml(temp_prompts_dir: Path) -> Path:
    """创建示例提示词 YAML 文件"""
    yaml_content = """
name: "测试角色"
character_prompt: |
  你是一个测试角色，会用简洁方式回答。
  你会把 {master_name} 作为称呼。
dialogue_examples:
  - scenario: "问候"
    user: "你好"
    bot: "你好呀，老师。"
error_messages:
  default: "测试默认错误消息"
"""
    yaml_path = temp_prompts_dir / "test_prompt.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")
    return yaml_path


@pytest.fixture
def invalid_yaml_file(temp_prompts_dir: Path) -> Path:
    """创建无效的 YAML 文件"""
    yaml_path = temp_prompts_dir / "invalid.yaml"
    yaml_path.write_text("invalid: yaml: content: [", encoding="utf-8")
    return yaml_path


# ==================== 日志配置 ====================

@pytest.fixture(autouse=True)
def suppress_logging():
    """在测试中抑制日志输出"""
    import logging
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)
