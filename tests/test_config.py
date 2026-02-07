# 配置类测试
"""
测试 config.py 模块

覆盖内容：
- Config 类实例化
- API Key 验证
- Base URL 验证
- 默认值检查
- 验证错误处理
"""
import pytest
from pydantic import ValidationError


class TestConfigValidation:
    """Config 配置验证测试"""
    
    def test_config_with_valid_api_key(self, valid_api_key: str):
        """测试使用有效 API Key 创建配置"""
        from mika_chat_core.config import Config
        
        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        
        assert config.gemini_api_key == valid_api_key
        assert len(config.get_effective_api_keys()) == 1
    
    def test_config_with_api_key_list(self, valid_api_key: str):
        """测试使用 API Key 列表创建配置"""
        from mika_chat_core.config import Config
        
        key_list = [
            "AIzaSyTest1234567890abcdefghij",
            "AIzaSyTest0987654321zyxwvutsrq"
        ]
        config = Config(gemini_api_key_list=key_list, gemini_master_id=123456789)
        
        assert len(config.gemini_api_key_list) == 2
        effective_keys = config.get_effective_api_keys()
        assert len(effective_keys) == 2
    
    def test_config_with_both_key_and_list(self, valid_api_key: str):
        """测试同时使用单个 Key 和 Key 列表"""
        from mika_chat_core.config import Config
        
        extra_key = "AIzaSyExtra123456789abcdefghij"
        config = Config(
            gemini_api_key=valid_api_key,
            gemini_api_key_list=[extra_key],
            gemini_master_id=123456789
        )
        
        effective_keys = config.get_effective_api_keys()
        assert valid_api_key in effective_keys
        assert extra_key in effective_keys
    
    def test_config_without_api_key_raises_error(self):
        """测试没有配置任何 API Key 时抛出验证错误"""
        from mika_chat_core.config import Config
        
        with pytest.raises(ValidationError) as exc_info:
            Config(gemini_api_key="", gemini_api_key_list=[], gemini_master_id=123456789)
        
        error_msg = str(exc_info.value)
        assert "gemini_api_key" in error_msg or "至少一个" in error_msg
    
    def test_config_with_short_api_key_raises_error(self, invalid_api_key_short: str):
        """测试 API Key 过短时抛出验证错误"""
        from mika_chat_core.config import Config
        
        with pytest.raises(ValidationError) as exc_info:
            Config(gemini_api_key=invalid_api_key_short)
        
        error_msg = str(exc_info.value)
        assert "长度" in error_msg or "短" in error_msg
    
    def test_config_with_space_in_api_key_raises_error(self, invalid_api_key_with_space: str):
        """测试 API Key 包含空格时抛出验证错误"""
        from mika_chat_core.config import Config
        
        with pytest.raises(ValidationError) as exc_info:
            Config(gemini_api_key=invalid_api_key_with_space)
        
        error_msg = str(exc_info.value)
        assert "空格" in error_msg
    
    def test_config_strips_api_key_whitespace(self, valid_api_key: str):
        """测试 API Key 首尾空格会被自动去除"""
        from mika_chat_core.config import Config
        
        key_with_whitespace = f"  {valid_api_key}  "
        # 注意：这里会去除首尾空格但中间不能有空格
        # 根据代码逻辑，首先会 strip()，然后检查空格
        config = Config(gemini_api_key=f"{valid_api_key}  ", gemini_master_id=123456789)
        
        assert config.gemini_api_key == valid_api_key


class TestConfigBaseUrl:
    """Base URL 验证测试"""
    
    def test_valid_https_base_url(self, valid_api_key: str):
        """测试有效的 HTTPS Base URL"""
        from mika_chat_core.config import Config
        
        config = Config(
            gemini_api_key=valid_api_key,
            gemini_base_url="https://api.example.com/v1",
            gemini_master_id=123456789
        )
        
        assert config.gemini_base_url == "https://api.example.com/v1"
    
    def test_valid_http_base_url(self, valid_api_key: str):
        """测试有效的 HTTP Base URL（本地开发用）"""
        from mika_chat_core.config import Config
        
        config = Config(
            gemini_api_key=valid_api_key,
            gemini_base_url="http://localhost:8080/api",
            gemini_master_id=123456789
        )
        
        assert config.gemini_base_url == "http://localhost:8080/api"
    
    def test_base_url_trailing_slash_removed(self, valid_api_key: str):
        """测试 Base URL 尾部斜杠会被去除"""
        from mika_chat_core.config import Config
        
        config = Config(
            gemini_api_key=valid_api_key,
            gemini_base_url="https://api.example.com/v1/",
            gemini_master_id=123456789
        )
        
        assert config.gemini_base_url == "https://api.example.com/v1"
        assert not config.gemini_base_url.endswith("/")
    
    def test_invalid_base_url_without_protocol(self, valid_api_key: str):
        """测试没有协议的 Base URL 抛出错误"""
        from mika_chat_core.config import Config
        
        with pytest.raises(ValidationError) as exc_info:
            Config(
                gemini_api_key=valid_api_key,
                gemini_base_url="api.example.com/v1",
                gemini_master_id=123456789
            )
        
        error_msg = str(exc_info.value)
        assert "http" in error_msg.lower()
    
    def test_empty_base_url_raises_error(self, valid_api_key: str):
        """测试空 Base URL 抛出错误"""
        from mika_chat_core.config import Config
        
        with pytest.raises(ValidationError):
            Config(
                gemini_api_key=valid_api_key,
                gemini_base_url="",
                gemini_master_id=123456789
            )


class TestConfigDefaults:
    """配置默认值测试"""
    
    def test_default_model(self, valid_api_key: str):
        """测试默认模型配置"""
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)

        # 默认主模型应与插件配置保持一致
        assert config.gemini_model == "gemini-3-pro-high"
    
    def test_default_base_url(self, valid_api_key: str):
        """测试默认 Base URL"""
        from mika_chat_core.config import Config
        
        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        
        assert "generativelanguage.googleapis.com" in config.gemini_base_url
    
    def test_default_max_context(self, valid_api_key: str):
        """测试默认上下文长度"""
        from mika_chat_core.config import Config
        
        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        
        assert config.gemini_max_context == 40
    
    def test_default_max_images(self, valid_api_key: str):
        """测试默认最大图片数"""
        from mika_chat_core.config import Config
        
        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        
        assert config.gemini_max_images == 10
    
    def test_default_master_name(self, valid_api_key: str):
        """测试默认主人称呼"""
        from mika_chat_core.config import Config
        
        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        
        assert config.gemini_master_name == "Sensei"
    
    def test_default_validate_on_startup(self, valid_api_key: str):
        """测试默认启动验证选项"""
        from mika_chat_core.config import Config
        
        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        
        assert config.gemini_validate_on_startup is True
    
    def test_default_forward_threshold(self, valid_api_key: str):
        """测试默认转发阈值"""
        from mika_chat_core.config import Config
        
        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        
        assert config.gemini_forward_threshold == 300

    def test_default_long_reply_image_fallback(self, valid_api_key: str):
        """测试长回复图片兜底默认配置"""
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)

        assert config.gemini_long_reply_image_fallback_enabled is True
        assert config.gemini_long_reply_image_max_chars == 12000
        assert config.gemini_long_reply_image_max_width == 960
        assert config.gemini_long_reply_image_font_size == 24
    
    def test_default_group_whitelist_empty(self, valid_api_key: str):
        """测试默认群白名单为空"""
        from mika_chat_core.config import Config
        
        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        
        assert config.gemini_group_whitelist == []

    def test_default_search_cache_settings(self, valid_api_key: str):
        """测试搜索缓存默认配置"""
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)

        assert config.gemini_search_cache_ttl_seconds == 60
        assert config.gemini_search_cache_max_size == 100

    def test_default_external_search_p0_settings(self, valid_api_key: str):
        """测试外置搜索 P0 默认配置"""
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)

        assert config.gemini_search_min_query_length == 4
        assert config.gemini_search_max_injection_results == 6


class TestConfigSectionViews:
    """配置分层访问器测试（P1）。"""

    def test_get_core_config(self, valid_api_key: str):
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        core = config.get_core_config()

        assert core["api_key"] == valid_api_key
        assert core["model"] == config.gemini_model
        assert core["max_context"] == config.gemini_max_context

    def test_get_search_config(self, valid_api_key: str):
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        search = config.get_search_config()

        assert search["cache_ttl_seconds"] == config.gemini_search_cache_ttl_seconds
        assert search["cache_max_size"] == config.gemini_search_cache_max_size
        assert search["llm_gate_enabled"] == config.gemini_search_llm_gate_enabled

    def test_get_image_config(self, valid_api_key: str):
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        image = config.get_image_config()

        assert image["max_images"] == config.gemini_max_images
        assert image["download_concurrency"] == config.gemini_image_download_concurrency
        assert image["cache_max_entries"] == config.gemini_image_cache_max_entries

    def test_get_proactive_config(self, valid_api_key: str):
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        proactive = config.get_proactive_config()

        assert proactive["rate"] == config.gemini_proactive_rate
        assert proactive["cooldown_seconds"] == config.gemini_proactive_cooldown
        assert proactive["heat_threshold"] == config.gemini_heat_threshold

    def test_get_observability_config(self, valid_api_key: str):
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        obs = config.get_observability_config()

        assert obs["prometheus_enabled"] == config.gemini_metrics_prometheus_enabled
        assert obs["health_api_probe_enabled"] == config.gemini_health_check_api_probe_enabled
        assert (
            obs["health_api_probe_timeout_seconds"]
            == config.gemini_health_check_api_probe_timeout_seconds
        )
        assert obs["health_api_probe_ttl_seconds"] == config.gemini_health_check_api_probe_ttl_seconds


class TestObservabilityValidation:
    """可观测性配置校验测试（P2）。"""

    def test_default_observability_values(self, valid_api_key: str):
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)
        assert config.gemini_metrics_prometheus_enabled is True
        assert config.gemini_health_check_api_probe_enabled is False
        assert config.gemini_health_check_api_probe_timeout_seconds == 3.0
        assert config.gemini_health_check_api_probe_ttl_seconds == 30

    def test_invalid_health_probe_timeout(self, valid_api_key: str):
        from mika_chat_core.config import Config

        with pytest.raises(ValidationError):
            Config(
                gemini_api_key=valid_api_key,
                gemini_master_id=123456789,
                gemini_health_check_api_probe_timeout_seconds=0,
            )

    def test_invalid_health_probe_ttl(self, valid_api_key: str):
        from mika_chat_core.config import Config

        with pytest.raises(ValidationError):
            Config(
                gemini_api_key=valid_api_key,
                gemini_master_id=123456789,
                gemini_health_check_api_probe_ttl_seconds=0,
            )

    def test_default_builtin_search_settings(self, valid_api_key: str):
        """测试内置搜索默认配置"""
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)

        assert config.gemini_enable_builtin_search is False

    def test_default_llm_search_gate_settings(self, valid_api_key: str):
        """测试外置搜索 LLM gate 默认配置"""
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)

        assert config.gemini_search_llm_gate_enabled is False
        assert config.gemini_search_llm_gate_fallback_mode == "strong_timeliness"
        assert config.gemini_search_classify_temperature == 0.0
        assert config.gemini_search_classify_max_tokens == 256
        assert config.gemini_search_classify_cache_ttl_seconds == 60
        assert config.gemini_search_classify_cache_max_size == 200

    def test_default_tool_security_settings(self, valid_api_key: str):
        """测试工具安全默认配置"""
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)

        assert "web_search" in config.gemini_tool_allowlist
        assert config.gemini_tool_result_max_chars == 4000

    def test_default_image_performance_settings(self, valid_api_key: str):
        """测试图片性能默认配置"""
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)

        assert config.gemini_image_download_concurrency == 3
        assert config.gemini_image_cache_max_entries == 200

    def test_default_proactive_keyword_cooldown(self, valid_api_key: str):
        """测试关键词冷却默认配置"""
        from mika_chat_core.config import Config

        config = Config(gemini_api_key=valid_api_key, gemini_master_id=123456789)

        assert config.gemini_proactive_keyword_cooldown == 5


class TestConfigApiKeyList:
    """API Key 列表验证测试"""
    
    def test_empty_strings_filtered_from_list(self):
        """测试空字符串会从 Key 列表中过滤"""
        from mika_chat_core.config import Config
        
        key_list = [
            "AIzaSyTest1234567890abcdefghij",
            "",
            "   ",
            "AIzaSyTest0987654321zyxwvutsrq"
        ]
        config = Config(gemini_api_key_list=key_list, gemini_master_id=123456789)
        
        # 空字符串应该被过滤掉
        assert len(config.gemini_api_key_list) == 2
    
    def test_short_key_in_list_raises_error(self):
        """测试列表中包含过短的 Key 抛出错误"""
        from mika_chat_core.config import Config
        
        key_list = [
            "AIzaSyTest1234567890abcdefghij",
            "short"  # 过短
        ]
        
        with pytest.raises(ValidationError) as exc_info:
            Config(gemini_api_key_list=key_list, gemini_master_id=123456789)
        
        error_msg = str(exc_info.value)
        assert "长度" in error_msg or "#2" in error_msg
    
    def test_key_with_space_in_list_raises_error(self):
        """测试列表中包含空格的 Key 抛出错误"""
        from mika_chat_core.config import Config
        
        key_list = [
            "AIzaSy Test1234567890abcdefghij"  # 包含空格
        ]
        
        with pytest.raises(ValidationError) as exc_info:
            Config(gemini_api_key_list=key_list, gemini_master_id=123456789)
        
        error_msg = str(exc_info.value)
        assert "空格" in error_msg


class TestConfigEffectiveKeys:
    """有效 API Key 获取测试"""
    
    def test_get_effective_keys_deduplicates(self):
        """测试获取有效 Key 时会去重"""
        from mika_chat_core.config import Config
        
        same_key = "AIzaSyTest1234567890abcdefghij"
        config = Config(
            gemini_api_key=same_key,
            gemini_api_key_list=[same_key, same_key],
            gemini_master_id=123456789
        )
        
        effective_keys = config.get_effective_api_keys()
        
        # 应该去重
        assert len(effective_keys) == 1
        assert effective_keys[0] == same_key
    
    def test_get_effective_keys_combines_both_sources(self):
        """测试有效 Key 列表合并单个 Key 和列表"""
        from mika_chat_core.config import Config
        
        single_key = "AIzaSySingle12345678901234567"
        list_keys = [
            "AIzaSyList0001234567890123456",
            "AIzaSyList0009876543210987654"
        ]
        
        config = Config(
            gemini_api_key=single_key,
            gemini_api_key_list=list_keys,
            gemini_master_id=123456789
        )
        
        effective_keys = config.get_effective_api_keys()
        
        assert single_key in effective_keys
        for key in list_keys:
            assert key in effective_keys
