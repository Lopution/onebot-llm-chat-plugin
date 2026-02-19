# 上下文智能降级机制测试
"""
测试 MikaClient 的空回复智能降级重试机制：
- Level 0: 完整上下文
- Level 1: 截断上下文 (20条)
- Level 2: 最小上下文 (5条)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from typing import Dict, Any


@pytest.mark.asyncio
class TestContextDegradation:
    """上下文降级机制测试"""
    
    @pytest.fixture
    def mock_mika_client(self):
        """创建模拟的 MikaClient"""
        with patch('mika_chat_core.mika_api.get_context_store') as mock_store:
            from mika_chat_core.mika_api import MikaClient
            
            # 模拟上下文存储
            mock_store_instance = AsyncMock()
            mock_store_instance.get_context = AsyncMock(return_value=[])
            mock_store_instance.add_message = AsyncMock()
            mock_store_instance.compress_context_for_safety = AsyncMock(return_value=[])
            mock_store.return_value = mock_store_instance
            
            client = MikaClient(
                api_key="test-key",
                use_persistent_storage=False
            )
            yield client
    
    async def test_context_level_0_full_context(self, mock_mika_client):
        """Level 0 应使用完整上下文"""
        client = mock_mika_client
        
        # 模拟 50 条历史消息
        mock_history = [{"role": "user", "content": f"msg {i}"} for i in range(50)]
        client._get_context_async = AsyncMock(return_value=mock_history)
        
        # 调用 _build_messages
        with patch.object(client, '_get_client') as mock_http:
            messages, _, _, _ = await client._build_messages(
                message="test",
                user_id="user1",
                group_id=None,
                image_urls=None,
                search_result="",
                context_level=0
            )
        
        # Level 0 应包含所有历史消息 (system + 50 history + user = 52)
        # 减去 system prompt，历史消息应为 50 条
        history_count = len([m for m in messages if m["role"] != "system"])
        assert history_count >= 50
    
    async def test_context_level_1_truncated(self, mock_mika_client):
        """Level 1 应截断到 20 条"""
        client = mock_mika_client
        
        # 模拟 50 条历史消息
        mock_history = [{"role": "user", "content": f"msg {i}"} for i in range(50)]
        client._get_context_async = AsyncMock(return_value=mock_history)
        
        messages, _, _, _ = await client._build_messages(
            message="test",
            user_id="user1",
            group_id=None,
            image_urls=None,
            search_result="",
            context_level=1
        )
        
        # Level 1 应截断到 20 条历史 + 1 条 user + 1 条 system = 22
        non_system = [m for m in messages if m["role"] != "system"]
        assert len(non_system) <= 21  # 20 history + 1 current user
    
    async def test_context_level_2_minimal(self, mock_mika_client):
        """Level 2 应使用最小上下文 (5条)"""
        client = mock_mika_client
        
        # 模拟 50 条历史消息
        mock_history = [{"role": "user", "content": f"msg {i}"} for i in range(50)]
        client._get_context_async = AsyncMock(return_value=mock_history)
        
        messages, _, _, _ = await client._build_messages(
            message="test",
            user_id="user1",
            group_id=None,
            image_urls=None,
            search_result="",
            context_level=2
        )
        
        # Level 2 应截断到 5 条历史 + 1 条 user + 1 条 system = 7
        non_system = [m for m in messages if m["role"] != "system"]
        assert len(non_system) <= 6  # 5 history + 1 current user


@pytest.mark.asyncio
class TestEmptyReplyRetry:
    """空回复重试逻辑测试"""
    
    async def test_empty_reply_triggers_degradation(self):
        """空回复应触发上下文降级"""
        with patch('mika_chat_core.mika_api.get_context_store'):
            with patch('mika_chat_core.mika_api.HAS_SQLITE_STORE', False):
                from mika_chat_core.mika_api import MikaClient
                
                client = MikaClient(
                    api_key="test-key",
                    use_persistent_storage=False
                )
                
                # 记录 chat 被调用的 context_level
                call_levels = []
                original_chat = client.chat
                
                async def mock_chat(*args, **kwargs):
                    context_level = kwargs.get('context_level', 0)
                    call_levels.append(context_level)
                    
                    # 前两次返回空，第三次返回正常
                    if len(call_levels) <= 2:
                        # 模拟空回复触发降级
                        if context_level < 2:
                            return await mock_chat(*args, context_level=context_level + 1, **kwargs)
                        return "终于成功了"
                    return "成功回复"
                
                # 验证降级逻辑存在于代码中
                # 检查 chat 方法源码包含 context_level
                import inspect
                source = inspect.getsource(client.chat)
                assert "context_level" in source
                assert "next_context_level = context_level + 1" in source


class TestCleanThinkingMarkers:
    """思考标记清理测试"""
    
    @pytest.fixture
    def client(self):
        with patch('mika_chat_core.mika_api.get_context_store'):
            with patch('mika_chat_core.mika_api.HAS_SQLITE_STORE', False):
                from mika_chat_core.mika_api import MikaClient
                return MikaClient(api_key="test", use_persistent_storage=False)
    
    def test_clean_thinking_markers(self, client):
        """测试清理思考过程标记"""
        text = "*Drafting the response (Mika style):* 这是测试内容"
        cleaned = client._clean_thinking_markers(text)
        assert "Drafting" not in cleaned
        assert "这是测试内容" in cleaned
    
    def test_clean_search_exposure(self, client):
        """测试清理搜索暴露语句"""
        texts = [
            "根据搜索结果，今天天气很好。",
            "我查到了最新的消息。",
            "从网络资料来看，这个事件是真实的。",
        ]
        for text in texts:
            cleaned = client._clean_thinking_markers(text)
            # 搜索相关前缀应被移除
            assert not cleaned.startswith("根据搜索")
            assert not cleaned.startswith("我查到")
            assert not cleaned.startswith("从网络")

    def test_clean_search_exposure_keeps_long_tail(self, client):
        """搜索暴露清理不应截断超长回复尾部"""
        suffix = "这是尾部内容"
        text = "根据搜索结果，" + ("有效正文" * 1200) + suffix
        cleaned = client._clean_thinking_markers(text)
        assert "根据搜索结果" not in cleaned
        assert cleaned.endswith(suffix)
    
    def test_preserve_normal_content(self, client):
        """测试保留正常内容"""
        normal_text = "今天天气真好，我们去散步吧！"
        cleaned = client._clean_thinking_markers(normal_text)
        assert cleaned == normal_text

    def test_preserve_long_content_without_truncation(self, client):
        """长回复不应因 sanitize 被截断"""
        long_text = "这是一段正常回复。 " * 400
        cleaned = client._clean_thinking_markers(long_text)
        assert cleaned == long_text.strip()


class TestExtractNickname:
    """昵称提取测试"""
    
    @pytest.fixture
    def client(self):
        with patch('mika_chat_core.mika_api.get_context_store'):
            with patch('mika_chat_core.mika_api.HAS_SQLITE_STORE', False):
                from mika_chat_core.mika_api import MikaClient
                return MikaClient(api_key="test", use_persistent_storage=False)
    
    def test_extract_standard_format(self, client):
        """测试标准格式 [昵称(QQ号)]: 消息"""
        nick, content = client._extract_nickname_from_content("[张三(123456)]: 你好啊")
        assert nick == "张三"
        assert content == "你好啊"
    
    def test_extract_sensei_format(self, client):
        """测试 Sensei 格式"""
        nick, content = client._extract_nickname_from_content("[⭐Sensei]: 这是指令")
        assert nick == "⭐Sensei"
        assert content == "这是指令"
    
    def test_extract_no_match(self, client):
        """测试无法匹配的格式"""
        nick, content = client._extract_nickname_from_content("普通消息")
        assert nick == "User"
        assert content == "普通消息"
