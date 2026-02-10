# 搜索引擎测试
"""
测试 utils/search_engine.py 模块

覆盖内容：
- should_search() 时效性关键词检测
- classify_topic_for_search() 智能分类
- serper_search() 搜索功能
- 缓存机制
- 错误处理
- 结果排序和截断
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
import httpx


class TestShouldSearch:
    """时效性关键词检测测试"""
    
    def test_should_search_with_time_keyword_latest(self):
        """测试包含'最新'关键词时返回 True"""
        from mika_chat_core.utils.search_engine import should_search
        
        assert should_search("最新的iPhone发布了吗") is True
    
    def test_should_search_with_time_keyword_today(self):
        """测试包含'今天'关键词时返回 True"""
        from mika_chat_core.utils.search_engine import should_search
        
        assert should_search("今天有什么新闻") is True
    
    def test_should_search_with_time_keyword_now(self):
        """测试包含'现在'关键词时返回 True"""
        from mika_chat_core.utils.search_engine import should_search

        # 本地时间问题应不触发外部搜索
        assert should_search("现在几点了") is False
    
    def test_should_search_with_time_keyword_recent(self):
        """测试包含'最近'关键词时返回 True"""
        from mika_chat_core.utils.search_engine import should_search
        
        assert should_search("最近有什么好看的电影") is True
    
    def test_should_search_with_news_keyword(self):
        """测试包含'新闻'关键词时返回 True"""
        from mika_chat_core.utils.search_engine import should_search
        
        assert should_search("科技新闻") is True
    
    def test_should_search_with_match_keyword(self):
        """测试包含'比赛'关键词时返回 True"""
        from mika_chat_core.utils.search_engine import should_search
        
        assert should_search("LPL比赛谁赢了") is True
    
    def test_should_search_with_price_keyword(self):
        """测试包含'价格'关键词时返回 True"""
        from mika_chat_core.utils.search_engine import should_search
        
        assert should_search("这个产品价格是多少") is True
    
    def test_should_search_with_weather_keyword(self):
        """测试包含'天气'关键词时返回 True"""
        from mika_chat_core.utils.search_engine import should_search
        
        assert should_search("北京天气怎么样") is True
    
    def test_should_search_without_keyword(self):
        """测试无时效性关键词不触发搜索"""
        from mika_chat_core.utils.search_engine import should_search
        
        assert should_search("你好，我叫小明") is False
        assert should_search("帮我写一首诗") is False
        assert should_search("什么是人工智能") is False
    
    def test_should_search_with_question_mark(self):
        """测试问号本身不触发搜索（需要关键词）"""
        from mika_chat_core.utils.search_engine import should_search
        
        # 单纯问号不触发
        assert should_search("你是谁？") is False
        # 带时效性关键词的问题触发
        assert should_search("今天天气怎么样？") is True

    def test_should_search_weak_time_keyword_in_chat_should_not_trigger(self):
        """弱时间词出现在闲聊里不应触发搜索"""
        from mika_chat_core.utils.search_engine import should_search

        assert should_search("我今天好累") is False

    def test_should_search_weak_time_keyword_with_question_signal_triggers(self):
        """弱时间词 + 问句信号时可触发搜索（如今天+天气/新闻等已覆盖，这里测试一般问句）"""
        from mika_chat_core.utils.search_engine import should_search

        assert should_search("今天是什么日子？") is True
    
    def test_should_search_with_ai_keyword_combo(self):
        """测试 AI 关键词 + 最好/最强组合"""
        from mika_chat_core.utils.search_engine import should_search
        
        assert should_search("现在最好的AI模型是哪个") is True
        assert should_search("GPT和Claude哪个最强") is True
        assert should_search("推荐一个好用的gemini") is True
    
    def test_should_search_with_ai_what_is(self):
        """测试 AI 关键词 + '是什么' 组合"""
        from mika_chat_core.utils.search_engine import should_search
        
        assert should_search("claude是什么") is True
        assert should_search("什么是deepseek") is True
    
    def test_should_search_empty_string(self):
        """测试空字符串返回 False"""
        from mika_chat_core.utils.search_engine import should_search
        
        assert should_search("") is False


class TestClassifyTopic:
    """智能分类测试"""
    
    @pytest.mark.asyncio
    async def test_classify_topic_factual(self):
        """测试事实性问题分类"""
        from mika_chat_core.utils.search_engine import classify_topic_for_search
        
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"needs_search": true, "topic": "科技产品", "search_query": "iPhone 16 价格"}'
                }
            }]
        }
        
        # Act
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client
            
            needs_search, topic, query = await classify_topic_for_search(
                "iPhone 16 多少钱",
                api_key="test-key",
                base_url="https://api.example.com/v1"
            )

        # JSON mode：应携带 response_format={type: json_object}
        called_json = mock_client.post.call_args.kwargs.get("json")
        assert called_json.get("response_format") == {"type": "json_object"}
        
        # Assert
        assert needs_search is True
        assert topic == "科技产品"
        assert "iPhone" in query


class TestClassifyJsonModeAndQuerySanitize:
    @pytest.mark.asyncio
    async def test_classify_topic_query_normalized_and_result_normalized(self):
        """分类器前后都应做 normalize_search_query：去掉 [昵称(QQ)]/@/机器人名等噪声，并截断。"""
        from mika_chat_core.utils.search_engine import classify_topic_for_search
        from mika_chat_core.utils import search_engine

        # Arrange: mock LLM 返回包含噪声的 search_query
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"needs_search": true, "topic": "新闻", "search_query": "@mika [小明(123456)]: 请帮我查一下 Kimi K2 发布  谢谢"}'
                    }
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            # Act
            needs_search, topic, query = await classify_topic_for_search(
                "[小明(123456)]: @mika 请帮我查一下 Kimi K2 发布  谢谢",
                api_key="test-key",
                base_url="https://api.example.com/v1",
            )

        assert needs_search is True
        assert topic == "新闻"
        # 前后清洗后的 query 不应包含这些噪声
        lowered = query.lower()
        assert "mika" not in lowered
        assert "@" not in query
        assert "(123456)" not in query
        assert "请" not in query  # 礼貌词应被移除（normalize 起始短语）
        assert "谢谢" not in query

        # 还要确保最终 query 是规范化结果（serper_search 也会 normalize，但这里验证 classify 已处理）
        # 且有长度上限（默认 64）
        assert len(query) <= 64

    @pytest.mark.asyncio
    async def test_classify_topic_overcompressed_query_fallback_to_message(self):
        """当分类器把复杂问题压缩成单词时，应回退到规范化后的原问题。"""
        from mika_chat_core.utils.search_engine import classify_topic_for_search

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"needs_search": true, "topic": "科技资讯", "search_query": "iOS"}'
                    }
                }
            ]
        }

        message = "苹果的ios26.3系统什么时候推送，现在内测都有什么功能"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            needs_search, topic, query = await classify_topic_for_search(
                message,
                api_key="test-key",
                base_url="https://api.example.com/v1",
            )

        assert needs_search is True
        assert topic == "科技资讯"
        assert query != "iOS"
        assert "ios26.3" in query.lower()
        assert "推送" in query


    @pytest.mark.asyncio
    async def test_classify_topic_response_format_4xx_downgrade_retry(self):
        """代理不支持 response_format 时，应对分类器做一次无 response_format 的降级重试。"""
        from mika_chat_core.utils.search_engine import classify_topic_for_search

        # first: 400
        bad = MagicMock()
        bad.status_code = 400
        bad.text = "unsupported response_format"

        good = MagicMock()
        good.status_code = 200
        good.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"needs_search": true, "topic": "科技", "search_query": "Claude 3.5 发布"}'
                    }
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.post = AsyncMock(side_effect=[bad, good])
            mock_client_class.return_value = mock_client

            needs_search, topic, query = await classify_topic_for_search(
                "Claude 3.5 什么时间发布",
                api_key="test-key",
                base_url="https://api.example.com/v1",
            )

        assert needs_search is True
        assert topic == "科技"
        assert query

        # 第一次请求应包含 response_format，第二次（降级）应不包含
        first_json = mock_client.post.call_args_list[0].kwargs.get("json")
        second_json = mock_client.post.call_args_list[1].kwargs.get("json")
        assert first_json.get("response_format") == {"type": "json_object"}
        assert "response_format" not in second_json

    @pytest.mark.asyncio
    async def test_classify_topic_anthropic_skips_json_mode_field(self):
        """Anthropic 原生 provider 不应发送 response_format。"""
        from mika_chat_core.utils.search_engine import classify_topic_for_search

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"needs_search": true, "topic": "科技", "search_query": "Claude 4 发布"}',
                }
            ],
            "stop_reason": "end_turn",
        }

        with patch("httpx.AsyncClient") as mock_client_class, patch(
            "mika_chat_core.utils.search_classifier.plugin_config.llm_provider",
            "anthropic",
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            needs_search, topic, query = await classify_topic_for_search(
                "Claude 4 什么时候发布",
                api_key="test-key",
                base_url="https://api.anthropic.com/v1",
            )

        assert needs_search is True
        assert topic == "科技"
        assert query
        called_json = mock_client.post.call_args.kwargs.get("json")
        assert "response_format" not in called_json
        assert mock_client.post.call_count == 1
    
    @pytest.mark.asyncio
    async def test_classify_topic_opinion(self):
        """测试观点性问题分类"""
        from mika_chat_core.utils.search_engine import classify_topic_for_search
        
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"needs_search": false, "topic": "闲聊", "search_query": ""}'
                }
            }]
        }
        
        # Act
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client
            
            needs_search, topic, query = await classify_topic_for_search(
                "你觉得什么颜色好看",
                api_key="test-key",
                base_url="https://api.example.com/v1"
            )
        
        # Assert
        assert needs_search is False
        assert topic == "闲聊"
    
    @pytest.mark.asyncio
    async def test_classify_topic_cache(self):
        """测试分类结果（搜索结果）缓存"""
        from mika_chat_core.utils.search_engine import (
            _get_cache_key, _get_cached_result, _set_cache, clear_search_cache
        )
        
        # 清空缓存
        clear_search_cache()
        
        # Arrange
        query = "测试查询"
        result = "测试结果"
        
        # Act - 设置缓存
        _set_cache(query, result)
        
        # Assert - 获取缓存
        cached = _get_cached_result(query)
        assert cached == result
        
        # 清理
        clear_search_cache()
        assert _get_cached_result(query) is None


class TestClassifyFallbackStrongTimeliness:
    """分类失败时强时效回退判定测试"""

    def test_strong_timeliness_hits(self):
        from mika_chat_core.utils.search_engine import should_fallback_strong_timeliness

        assert should_fallback_strong_timeliness("比赛结果出来了吗") is True
        assert should_fallback_strong_timeliness("发布了什么新模型") is True

    def test_weak_time_without_strong_signal_not_hit(self):
        from mika_chat_core.utils.search_engine import should_fallback_strong_timeliness

        # 弱时间词本身不应回退
        assert should_fallback_strong_timeliness("我今天好累") is False

    def test_local_datetime_not_hit(self):
        from mika_chat_core.utils.search_engine import should_fallback_strong_timeliness

        assert should_fallback_strong_timeliness("现在几点了") is False
    
    @pytest.mark.asyncio
    async def test_classify_topic_with_context(self):
        """测试带上下文的分类"""
        from mika_chat_core.utils.search_engine import classify_topic_for_search
        
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": '{"needs_search": true, "topic": "科技产品", "search_query": "iPhone 16 价格"}'
                }
            }]
        }
        
        context = [
            {"role": "user", "content": "iPhone 16 怎么样"},
            {"role": "assistant", "content": "iPhone 16 是苹果最新的手机"}
        ]
        
        # Act
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client
            
            needs_search, topic, query = await classify_topic_for_search(
                "它现在多少钱",
                api_key="test-key",
                base_url="https://api.example.com/v1",
                context=context
            )
        
        # Assert
        assert needs_search is True
    
    @pytest.mark.asyncio
    async def test_classify_topic_api_error(self):
        """测试 API 错误处理"""
        from mika_chat_core.utils.search_engine import classify_topic_for_search
        
        # Arrange
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        
        # Act
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client
            
            needs_search, topic, query = await classify_topic_for_search(
                "测试问题",
                api_key="test-key",
                base_url="https://api.example.com/v1"
            )
        
        # Assert - 错误时返回默认值
        assert needs_search is False
        assert topic == "未知"
        assert query == ""

    @pytest.mark.asyncio
    async def test_classify_topic_uses_cache_to_avoid_second_call(self):
        """同一 message+context 在 TTL 内应命中分类缓存，避免重复调用 LLM"""
        from mika_chat_core.utils.search_engine import classify_topic_for_search, clear_classify_cache

        clear_classify_cache()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": '{"needs_search": true, "topic": "科技产品", "search_query": "iPhone 16 价格"}'
                    }
                }
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class, patch(
            "mika_chat_core.utils.search_engine.plugin_config.gemini_search_classify_cache_ttl_seconds",
            60,
        ), patch(
            "mika_chat_core.utils.search_engine.plugin_config.gemini_search_classify_cache_max_size",
            200,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            r1 = await classify_topic_for_search(
                "iPhone 16 多少钱",
                api_key="test-key",
                base_url="https://api.example.com/v1",
                context=[],
            )
            r2 = await classify_topic_for_search(
                "iPhone 16 多少钱",
                api_key="test-key",
                base_url="https://api.example.com/v1",
                context=[],
            )

        assert r1 == r2
        assert mock_client.post.call_count == 1


class TestSerperSearch:
    """Serper 搜索测试"""
    
    @pytest.mark.asyncio
    async def test_serper_search_success(self):
        """测试成功搜索"""
        from mika_chat_core.utils import search_engine
        
        # Arrange
        original_key = search_engine.SERPER_API_KEY
        search_engine.SERPER_API_KEY = "test-api-key"
        
        # 清空缓存
        search_engine.clear_search_cache()
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "organic": [
                {
                    "title": "测试标题",
                    "link": "https://example.com/article",
                    "snippet": "这是一段测试摘要"
                }
            ]
        }
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        
        # Act
        with patch.object(search_engine, "_http_client", mock_client):
            result = await search_engine.serper_search("测试查询")
        
        # Assert
        assert "测试标题" in result
        assert "测试摘要" in result
        
        # 恢复
        search_engine.SERPER_API_KEY = original_key
    
    @pytest.mark.asyncio
    async def test_serper_search_api_error(self):
        """测试 API 错误处理"""
        from mika_chat_core.utils import search_engine
        
        # Arrange
        original_key = search_engine.SERPER_API_KEY
        search_engine.SERPER_API_KEY = "test-api-key"
        
        search_engine.clear_search_cache()
        
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("Error", request=MagicMock(), response=MagicMock())
        )
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        
        # Act
        with patch.object(search_engine, "_http_client", mock_client):
            result = await search_engine.serper_search("测试查询")
        
        # Assert - 错误时返回空字符串
        assert result == ""
        
        # 恢复
        search_engine.SERPER_API_KEY = original_key
    
    @pytest.mark.asyncio
    async def test_serper_search_rate_limit(self):
        """测试限流处理"""
        from mika_chat_core.utils import search_engine
        
        # Arrange
        original_key = search_engine.SERPER_API_KEY
        search_engine.SERPER_API_KEY = "test-api-key"
        
        search_engine.clear_search_cache()
        
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("Rate limited", request=MagicMock(), response=MagicMock())
        )
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        
        # Act
        with patch.object(search_engine, "_http_client", mock_client):
            result = await search_engine.serper_search("测试查询")
        
        # Assert
        assert result == ""
        
        # 恢复
        search_engine.SERPER_API_KEY = original_key
    
    @pytest.mark.asyncio
    async def test_serper_search_timeout(self):
        """测试超时处理"""
        from mika_chat_core.utils import search_engine
        
        # Arrange
        original_key = search_engine.SERPER_API_KEY
        search_engine.SERPER_API_KEY = "test-api-key"
        
        search_engine.clear_search_cache()
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
        
        # Act
        with patch.object(search_engine, "_http_client", mock_client):
            result = await search_engine.serper_search("测试查询")
        
        # Assert
        assert result == ""
        
        # 恢复
        search_engine.SERPER_API_KEY = original_key
    
    @pytest.mark.asyncio
    async def test_serper_search_no_api_key(self):
        """测试无 API Key 时跳过搜索"""
        from mika_chat_core.utils import search_engine
        
        # Arrange
        original_key = search_engine.SERPER_API_KEY
        search_engine.SERPER_API_KEY = ""  # 无 API Key
        
        # Act
        result = await search_engine.serper_search("测试查询")
        
        # Assert
        assert result == ""
        
        # 恢复
        search_engine.SERPER_API_KEY = original_key


class TestClassifyCache:
    def test_clear_classify_cache(self):
        from mika_chat_core.utils.search_engine import clear_classify_cache

        # 只验证函数存在且可调用
        clear_classify_cache()
    
    @pytest.mark.asyncio
    async def test_search_with_empty_query(self):
        """测试空查询处理"""
        from mika_chat_core.utils import search_engine
        
        # Arrange
        original_key = search_engine.SERPER_API_KEY
        search_engine.SERPER_API_KEY = "test-api-key"
        
        search_engine.clear_search_cache()
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"organic": []}
        
        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(return_value=mock_response)
        
        # Act
        with patch.object(search_engine, "_http_client", mock_client):
            result = await search_engine.serper_search("")
        
        # Assert - 空查询返回空结果
        assert result == ""
        
        # 恢复
        search_engine.SERPER_API_KEY = original_key

    @pytest.mark.asyncio
    async def test_serper_search_local_datetime_query_skipped(self):
        """本地时间/日期问题不应执行外部搜索"""
        from mika_chat_core.utils import search_engine

        original_key = search_engine.SERPER_API_KEY
        search_engine.SERPER_API_KEY = "test-api-key"

        # mock client：如果被调用就会失败
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.post = AsyncMock(side_effect=AssertionError("should not call external search"))

        with patch.object(search_engine, "_http_client", mock_client):
            result = await search_engine.serper_search("现在几点了")

        assert result == ""

        search_engine.SERPER_API_KEY = original_key


class TestSearchResultRanking:
    """搜索结果排序测试"""
    
    def test_search_result_ranking(self):
        """测试可信源排序"""
        from mika_chat_core.utils.search_engine import sort_by_relevance, is_trusted_source
        
        # Arrange
        results = [
            {"title": "未知来源", "link": "https://unknown.com/article"},
            {"title": "维基百科", "link": "https://wikipedia.org/wiki/Test"},
            {"title": "另一个未知来源", "link": "https://random.net/page"},
            {"title": "GitHub", "link": "https://github.com/test/repo"},
        ]
        
        # Act
        sorted_results = sort_by_relevance(results)
        
        # Assert - 可信来源应该排在前面
        assert is_trusted_source(sorted_results[0]["link"])
        assert is_trusted_source(sorted_results[1]["link"])
        # 验证可信来源
        trusted_titles = [r["title"] for r in sorted_results[:2]]
        assert "维基百科" in trusted_titles
        assert "GitHub" in trusted_titles
    
    def test_is_trusted_source(self):
        """测试可信来源检测"""
        from mika_chat_core.utils.search_engine import is_trusted_source
        
        # Assert
        assert is_trusted_source("https://wikipedia.org/wiki/AI") is True
        assert is_trusted_source("https://github.com/user/repo") is True
        assert is_trusted_source("https://zhihu.com/question/12345") is True
        assert is_trusted_source("https://arxiv.org/abs/1234.5678") is True
        assert is_trusted_source("https://random-blog.com/post") is False
        assert is_trusted_source("https://unknown-site.net/article") is False
    
    def test_search_result_truncation(self):
        """测试结果截断"""
        from mika_chat_core.utils.search_engine import sort_by_relevance
        
        # Arrange - 创建大量结果
        results = [
            {"title": f"结果{i}", "link": f"https://example.com/page{i}"}
            for i in range(20)
        ]
        
        # Act
        sorted_results = sort_by_relevance(results)
        
        # Assert - sort_by_relevance 不截断，只排序
        assert len(sorted_results) == 20  # 所有结果都保留
        
        # 截断在 serper_search 中处理（只取前 6 条）


class TestSearchCache:
    """搜索缓存测试"""
    
    def test_cache_set_and_get(self):
        """测试缓存设置和获取"""
        from mika_chat_core.utils.search_engine import (
            _get_cached_result, _set_cache, clear_search_cache
        )
        
        # 清空缓存
        clear_search_cache()
        
        # Arrange
        query = "缓存测试查询"
        result = "缓存测试结果"
        
        # Act
        _set_cache(query, result)
        cached = _get_cached_result(query)
        
        # Assert
        assert cached == result
    
    def test_cache_expiry(self):
        """测试缓存过期"""
        from mika_chat_core.utils import search_engine
        from mika_chat_core.utils.search_engine import (
            _get_cached_result, _set_cache, _get_cache_key, clear_search_cache
        )
        
        # 清空缓存
        clear_search_cache()
        
        # Arrange
        query = "过期测试"
        result = "测试结果"
        
        # 设置缓存
        _set_cache(query, result)
        
        # 人为设置过期时间
        cache_key = _get_cache_key(query)
        search_engine._search_cache[cache_key] = (result, time.time() - 120)  # 2 分钟前
        
        # Act
        cached = _get_cached_result(query)
        
        # Assert - 缓存应该过期
        assert cached is None
    
    def test_cache_max_size(self):
        """测试缓存最大容量"""
        from mika_chat_core.utils import search_engine
        from mika_chat_core.utils.search_engine import (
            _set_cache, clear_search_cache, MAX_CACHE_SIZE
        )
        
        # 清空缓存
        clear_search_cache()
        
        # Arrange - 填满缓存
        for i in range(MAX_CACHE_SIZE + 10):
            _set_cache(f"query{i}", f"result{i}")
        
        # Assert - 缓存不应超过最大容量
        assert len(search_engine._search_cache) <= MAX_CACHE_SIZE
    
    def test_clear_cache(self):
        """测试清空缓存"""
        from mika_chat_core.utils import search_engine
        from mika_chat_core.utils.search_engine import (
            _set_cache, clear_search_cache
        )
        
        # Arrange
        _set_cache("test", "value")
        assert len(search_engine._search_cache) > 0
        
        # Act
        clear_search_cache()
        
        # Assert
        assert len(search_engine._search_cache) == 0


class TestJsonExtraction:
    """JSON 提取测试"""
    
    def test_extract_json_pure(self):
        """测试纯 JSON 提取"""
        from mika_chat_core.utils.search_engine import _extract_json_object
        
        text = '{"needs_search": true, "topic": "测试", "search_query": "查询"}'
        result = _extract_json_object(text)
        
        assert result is not None
        assert result["needs_search"] is True
        assert result["topic"] == "测试"
    
    def test_extract_json_markdown(self):
        """测试 Markdown 代码块包裹的 JSON"""
        from mika_chat_core.utils.search_engine import _extract_json_object
        
        text = '''```json
{"needs_search": false, "topic": "闲聊", "search_query": ""}
```'''
        result = _extract_json_object(text)
        
        assert result is not None
        assert result["needs_search"] is False
    
    def test_extract_json_with_extra_text(self):
        """测试 JSON 前后有额外文字"""
        from mika_chat_core.utils.search_engine import _extract_json_object
        
        text = '根据分析，结果是：{"needs_search": true, "topic": "新闻", "search_query": "最新新闻"} 以上是分析结果。'
        result = _extract_json_object(text)
        
        assert result is not None
        assert result["needs_search"] is True
    
    def test_extract_json_empty(self):
        """测试空文本"""
        from mika_chat_core.utils.search_engine import _extract_json_object
        
        assert _extract_json_object("") is None
        assert _extract_json_object(None) is None
    
    def test_extract_json_invalid(self):
        """测试无效 JSON"""
        from mika_chat_core.utils.search_engine import _extract_json_object
        
        text = "这不是 JSON 格式的文本"
        result = _extract_json_object(text)
        
        assert result is None


class TestTimelinessKeywords:
    """时效性关键词列表测试"""
    
    def test_timeliness_keywords_not_empty(self):
        """测试关键词列表不为空"""
        from mika_chat_core.utils.search_engine import TIMELINESS_KEYWORDS
        
        assert len(TIMELINESS_KEYWORDS) > 0
    
    def test_timeliness_keywords_contains_time_words(self):
        """测试关键词列表包含时间相关词汇"""
        from mika_chat_core.utils.search_engine import TIMELINESS_KEYWORDS
        
        time_words = ["最新", "现在", "目前", "今天", "最近"]
        for word in time_words:
            assert word in TIMELINESS_KEYWORDS
    
    def test_ai_keywords_not_empty(self):
        """测试 AI 关键词列表不为空"""
        from mika_chat_core.utils.search_engine import AI_KEYWORDS
        
        assert len(AI_KEYWORDS) > 0
        assert "gpt" in AI_KEYWORDS
        assert "claude" in AI_KEYWORDS
        assert "gemini" in AI_KEYWORDS


class TestTrustedDomains:
    """可信域名列表测试"""
    
    def test_trusted_domains_not_empty(self):
        """测试可信域名列表不为空"""
        from mika_chat_core.utils.search_engine import TRUSTED_DOMAINS
        
        assert len(TRUSTED_DOMAINS) > 0
    
    def test_trusted_domains_contains_common_sources(self):
        """测试可信域名列表包含常见来源"""
        from mika_chat_core.utils.search_engine import TRUSTED_DOMAINS
        
        expected_domains = [
            "wikipedia.org",
            "github.com",
            "zhihu.com",
            "arxiv.org"
        ]
        for domain in expected_domains:
            assert domain in TRUSTED_DOMAINS


class TestHttpClient:
    """HTTP 客户端测试"""
    
    @pytest.mark.asyncio
    async def test_get_http_client(self):
        """测试获取 HTTP 客户端"""
        from mika_chat_core.utils import search_engine
        
        # 重置客户端
        if search_engine._http_client:
            try:
                await search_engine._http_client.aclose()
            except RuntimeError:
                pass
        search_engine._http_client = None
        
        # Act
        client = await search_engine._get_http_client()
        
        # Assert
        assert client is not None
        assert not client.is_closed
        
        # 清理
        await client.aclose()
        search_engine._http_client = None

    @pytest.mark.asyncio
    async def test_get_http_client_recreates_on_loop_id_mismatch(self):
        """测试客户端记录的 loop_id 异常时会重建 HTTP 客户端。"""
        from mika_chat_core.utils import search_engine

        first_client = await search_engine._get_http_client()
        search_engine._http_client_loop_id = -1
        second_client = await search_engine._get_http_client()

        assert second_client is not first_client
        await search_engine.close_search_engine()
    
    @pytest.mark.asyncio
    async def test_close_search_engine(self):
        """测试关闭搜索引擎"""
        from mika_chat_core.utils import search_engine
        
        # 先获取客户端
        client = await search_engine._get_http_client()
        assert client is not None
        
        # Act
        await search_engine.close_search_engine()
        
        # Assert
        assert search_engine._http_client is None
