# Gemini API 客户端测试
"""
测试 gemini_api.py 模块

覆盖内容：
- GeminiClient 初始化
- API 调用（使用 mock）
- 错误处理
- 上下文管理
- API Key 轮询
"""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch


class TestGeminiAPIExceptions:
    """测试自定义异常类"""
    
    def test_gemini_api_error_basic(self):
        """测试基础 API 错误"""
        from gemini_chat.gemini_api import GeminiAPIError
        
        error = GeminiAPIError("Test error", status_code=400, retry_after=0)
        
        assert error.message == "Test error"
        assert error.status_code == 400
        assert error.retry_after == 0
        assert str(error) == "Test error"
    
    def test_rate_limit_error(self):
        """测试限流错误"""
        from gemini_chat.gemini_api import RateLimitError
        
        error = RateLimitError("Rate limit exceeded", status_code=429, retry_after=60)
        
        assert error.status_code == 429
        assert error.retry_after == 60
        assert isinstance(error, Exception)
    
    def test_authentication_error(self):
        """测试认证错误"""
        from gemini_chat.gemini_api import AuthenticationError
        
        error = AuthenticationError("Invalid API key", status_code=401)
        
        assert error.status_code == 401
        assert "Invalid API key" in error.message
    
    def test_server_error(self):
        """测试服务器错误"""
        from gemini_chat.gemini_api import ServerError
        
        error = ServerError("Internal server error", status_code=500)
        
        assert error.status_code == 500


class TestGeminiClientInit:
    """测试 GeminiClient 初始化"""
    
    def test_init_with_defaults(self):
        """测试使用默认参数初始化"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key-123")
            
            assert client.api_key == "test-key-123"
            assert client.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
            assert client.model == "gemini-3-flash"
            assert client.system_prompt == "你是一个友好的AI助手"
            assert client.max_context == 10
            assert client._use_persistent == False
    
    def test_init_with_custom_params(self):
        """测试使用自定义参数初始化"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(
                api_key="custom-key",
                base_url="https://custom.api.com/v1/",
                model="gemini-pro",
                system_prompt="自定义系统提示",
                max_context=20
            )
            
            assert client.api_key == "custom-key"
            assert client.base_url == "https://custom.api.com/v1"  # 应该去掉尾部斜杠
            assert client.model == "gemini-pro"
            assert client.system_prompt == "自定义系统提示"
            assert client.max_context == 20
    
    def test_init_with_api_key_list(self):
        """测试使用多个 API Key 初始化"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            key_list = ["key1", "key2", "key3"]
            client = GeminiClient(api_key="default-key", api_key_list=key_list)
            
            assert client.api_key_list == key_list
            assert client._key_index == 0
    
    def test_init_with_persistent_storage_disabled(self):
        """测试禁用持久化存储"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", True):
            client = GeminiClient(api_key="test-key", use_persistent_storage=False)
            
            assert client._use_persistent == False
            assert client._context_store is None
    
    def test_init_with_persistent_storage_unavailable(self):
        """测试持久化存储不可用时自动降级"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key", use_persistent_storage=True)
            
            # 即使要求使用持久化，但因为不可用所以应该是 False
            assert client._use_persistent == False
            assert client._context_store is None


class TestGeminiClientAPIKeyRotation:
    """测试 API Key 轮询"""
    
    def test_get_api_key_single(self):
        """测试单个 API Key"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="single-key")
            
            # 多次获取应该返回相同的 key
            assert client._get_api_key() == "single-key"
            assert client._get_api_key() == "single-key"
    
    def test_get_api_key_rotation(self):
        """测试 API Key 轮询"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            key_list = ["key1", "key2", "key3"]
            client = GeminiClient(api_key="default", api_key_list=key_list)
            
            # 应该按顺序轮询
            assert client._get_api_key() == "key1"
            assert client._get_api_key() == "key2"
            assert client._get_api_key() == "key3"
            # 回到开始
            assert client._get_api_key() == "key1"
            assert client._get_api_key() == "key2"


class TestGeminiClientContextManagement:
    """测试上下文管理（内存模式）"""
    
    def test_get_context_key_private(self):
        """测试私聊上下文 key 生成"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            key = client._get_context_key(user_id="user123")
            
            assert key == ("PRIVATE_CHAT", "user123")
    
    def test_get_context_key_group(self):
        """测试群聊上下文 key 生成"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            key = client._get_context_key(user_id="user123", group_id="group456")
            
            assert key == ("group456", "GROUP_CHAT")
    
    def test_add_to_context_memory_mode(self):
        """测试添加消息到上下文（内存模式）"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key", max_context=5)
            
            client._add_to_context("user123", "user", "Hello")
            client._add_to_context("user123", "assistant", "Hi there!")
            
            context = client._get_context("user123")
            
            assert len(context) == 2
            assert context[0]["role"] == "user"
            assert context[0]["content"] == "Hello"
            assert context[1]["role"] == "assistant"
            assert context[1]["content"] == "Hi there!"
    
    def test_context_truncation(self):
        """测试上下文超出限制时自动截断"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key", max_context=2)
            
            # 添加超过限制的消息（max_context * 2 = 4）
            for i in range(6):
                client._add_to_context("user123", "user", f"Message {i}")
            
            context = client._get_context("user123")
            
            # 应该只保留最后 4 条
            assert len(context) == 4
            assert context[0]["content"] == "Message 2"
            assert context[-1]["content"] == "Message 5"
    
    def test_clear_context_memory_mode(self):
        """测试清空上下文（内存模式）"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            client._add_to_context("user123", "user", "Hello")
            assert len(client._get_context("user123")) == 1
            
            client.clear_context("user123")
            assert len(client._get_context("user123")) == 0


class TestGeminiClientHTTPClient:
    """测试 HTTP 客户端管理"""
    
    @pytest.mark.asyncio
    async def test_get_client_creates_new(self):
        """测试首次获取创建新客户端"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            http_client = await client._get_client()
            
            assert http_client is not None
            assert isinstance(http_client, httpx.AsyncClient)
            
            await client.close()
    
    @pytest.mark.asyncio
    async def test_get_client_reuses_existing(self):
        """测试复用已存在的客户端"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            http_client1 = await client._get_client()
            http_client2 = await client._get_client()
            
            # 应该是同一个实例
            assert http_client1 is http_client2
            
            await client.close()
    
    @pytest.mark.asyncio
    async def test_close_client(self):
        """测试关闭 HTTP 客户端"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            http_client = await client._get_client()
            await client.close()
            
            # 客户端应该被关闭（close 后 _http_client 被设为 None）
            # 验证原始客户端已关闭或 _http_client 已被清理
            assert client._http_client is None or http_client.is_closed


@pytest.mark.asyncio
class TestGeminiClientChat:
    """测试 chat 方法"""
    
    async def test_chat_success(self, mock_httpx_client, mock_api_response_success):
        """测试成功的聊天请求"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            # Mock httpx client
            mock_httpx_client.post.return_value.json.return_value = mock_api_response_success
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                response = await client.chat("你好", user_id="user123")
                
                assert response == "你好！我是测试助手，很高兴见到你~"
                
                # 验证 API 被调用
                mock_httpx_client.post.assert_called_once()
                call_args = mock_httpx_client.post.call_args
                assert "/chat/completions" in call_args[0][0]
    
    async def test_chat_with_images(self, mock_httpx_client, mock_api_response_success):
        """测试带图片的聊天请求"""
        from gemini_chat.gemini_api import GeminiClient
        
        # 避免在测试里触发真实图片下载（会引入网络/DNS/线程池不确定性，且不影响本用例断言）
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False), patch(
            "gemini_chat.gemini_api.HAS_IMAGE_PROCESSOR",
            False,
        ):
            client = GeminiClient(api_key="test-key")
            
            mock_httpx_client.post.return_value.json.return_value = mock_api_response_success
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                response = await client.chat(
                    "看这张图片",
                    user_id="user123",
                    image_urls=["https://example.com/image.jpg"]
                )
                
                assert response == "你好！我是测试助手，很高兴见到你~"
                
                # 检查请求体包含图片
                call_args = mock_httpx_client.post.call_args
                request_body = call_args[1]["json"]
                user_message = request_body["messages"][-1]
                
                # 用户消息应该是列表格式（包含文本和图片）
                assert isinstance(user_message["content"], list)
                assert any(item["type"] == "image_url" for item in user_message["content"])
    
    async def test_chat_empty_response(self, mock_httpx_client, mock_api_response_empty):
        """测试空回复"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            mock_httpx_client.post.return_value.json.return_value = mock_api_response_empty
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                response = await client.chat("测试", user_id="user123")
                
                # 应该返回默认的空回复提示
                assert "走神" in response or "再说一次" in response
    
    async def test_chat_timeout_error(self, mock_httpx_client):
        """测试超时错误"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            # 模拟超时
            mock_httpx_client.post.side_effect = httpx.TimeoutException("Request timeout")
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                response = await client.chat("测试", user_id="user123")
                
                # 应该返回超时错误消息
                assert response == client._error_messages["timeout"].format(name=client.character_name)
    
    async def test_chat_rate_limit_error(self, mock_httpx_client):
        """测试 429 限流错误"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            # 模拟 429 响应
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.headers = {"Retry-After": "60"}
            mock_response.text = ""
            mock_httpx_client.post.return_value = mock_response
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                response = await client.chat("测试", user_id="user123")
                
                # 应该返回限流错误消息
                assert response == client._error_messages["rate_limit"].format(name=client.character_name)
    
    async def test_chat_authentication_error(self, mock_httpx_client):
        """测试 401 认证错误"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="invalid-key")
            
            # 模拟 401 响应
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.headers = {}
            mock_response.text = "Invalid API key"
            mock_httpx_client.post.return_value = mock_response
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                response = await client.chat("测试", user_id="user123")
                
                # 应该返回认证错误消息
                assert response == client._error_messages["auth_error"].format(name=client.character_name)
    
    async def test_chat_server_error_with_retry(self, mock_httpx_client, mock_api_response_success):
        """测试服务器错误自动重试"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            # 第一次返回 500，第二次成功
            mock_response_error = MagicMock()
            mock_response_error.status_code = 500
            mock_response_error.headers = {}
            mock_response_error.text = "Internal Server Error"
            
            mock_response_success = MagicMock()
            mock_response_success.status_code = 200
            mock_response_success.headers = {}
            mock_response_success.text = ""
            mock_response_success.json.return_value = mock_api_response_success
            mock_response_success.raise_for_status = MagicMock()
            
            mock_httpx_client.post.side_effect = [mock_response_error, mock_response_success]
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                with patch("asyncio.sleep", new_callable=AsyncMock):  # 跳过实际延迟
                    response = await client.chat("测试", user_id="user123", retry_count=1)
                    
                    # 应该成功（经过重试）
                    assert response == "你好！我是测试助手，很高兴见到你~"
                    
                    # 应该调用了两次
                    assert mock_httpx_client.post.call_count == 2
    
    async def test_chat_server_error_exhausted_retries(self, mock_httpx_client):
        """测试服务器错误重试耗尽"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            # 始终返回 500
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.headers = {}
            mock_response.text = "Internal Server Error"
            mock_httpx_client.post.return_value = mock_response
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                response = await client.chat("测试", user_id="user123", retry_count=0)
                
                # 应该返回服务器错误消息
                assert response == client._error_messages["server_error"].format(name=client.character_name)
    
    async def test_chat_content_filter_error(self, mock_httpx_client):
        """测试内容过滤错误"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            # 模拟内容过滤错误
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.headers = {}
            mock_response.text = '{"error": {"message": "Content blocked by safety filters"}}'
            mock_httpx_client.post.return_value = mock_response
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                response = await client.chat("敏感内容", user_id="user123")
                
                # 应该返回内容过滤错误消息
                assert response == client._error_messages["content_filter"].format(name=client.character_name)
    
    async def test_chat_unknown_error(self, mock_httpx_client):
        """测试未知错误"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            # 模拟未知异常
            mock_httpx_client.post.side_effect = Exception("Unexpected error")
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                response = await client.chat("测试", user_id="user123")
                
                # 应该返回未知错误消息
                assert response == client._error_messages["unknown"].format(name=client.character_name)
    
    async def test_chat_context_preserved(self, mock_httpx_client, mock_api_response_success):
        """测试上下文被正确保存"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            mock_httpx_client.post.return_value.json.return_value = mock_api_response_success
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                # 第一次对话
                await client.chat("第一条消息", user_id="user123")
                
                # 第二次对话
                await client.chat("第二条消息", user_id="user123")
                
                # 检查上下文
                context = client._get_context("user123")
                
                # 应该有 4 条消息（2轮对话 = 2条用户消息 + 2条助手消息）
                assert len(context) == 4
                assert context[0]["content"] == "第一条消息"
                assert context[2]["content"] == "第二条消息"
    
    async def test_chat_group_vs_private_context(self, mock_httpx_client, mock_api_response_success):
        """测试群聊和私聊上下文隔离"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            mock_httpx_client.post.return_value.json.return_value = mock_api_response_success
            
            with patch.object(client, "_get_client", return_value=mock_httpx_client):
                # 私聊
                await client.chat("私聊消息", user_id="user123")
                
                # 群聊
                await client.chat("群聊消息", user_id="user123", group_id="group456")
                
                # 检查上下文是分开的
                private_context = client._get_context("user123")
                group_context = client._get_context("user123", group_id="group456")
                
                assert len(private_context) == 2
                assert len(group_context) == 2
                assert private_context[0]["content"] == "私聊消息"
                assert group_context[0]["content"] == "群聊消息"


@pytest.mark.asyncio
class TestGeminiClientAsyncContext:
    """测试异步上下文管理"""
    
    async def test_get_context_async_memory_mode(self):
        """测试异步获取上下文（内存模式）"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            client._add_to_context("user123", "user", "测试消息")
            
            context = await client._get_context_async("user123")
            
            assert len(context) == 1
            assert context[0]["content"] == "测试消息"
    
    async def test_add_to_context_async_memory_mode(self):
        """测试异步添加上下文（内存模式）"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            await client._add_to_context_async("user123", "user", "异步消息")
            
            context = client._get_context("user123")
            
            assert len(context) == 1
            assert context[0]["content"] == "异步消息"
    
    async def test_clear_context_async_memory_mode(self):
        """测试异步清空上下文（内存模式）"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            client._add_to_context("user123", "user", "测试消息")
            assert len(client._get_context("user123")) == 1
            
            await client.clear_context_async("user123")
            
            context = await client._get_context_async("user123")
            assert len(context) == 0


class TestGeminiClientToolHandlers:
    """测试工具处理器注册"""
    
    def test_register_tool_handler(self):
        """测试注册工具处理器"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            def mock_search_handler(query: str):
                return f"搜索结果: {query}"
            
            client.register_tool_handler("search", mock_search_handler)
            
            assert "search" in client._tool_handlers
            assert client._tool_handlers["search"]("测试") == "搜索结果: 测试"
    
    def test_register_multiple_tool_handlers(self):
        """测试注册多个工具处理器"""
        from gemini_chat.gemini_api import GeminiClient
        
        with patch("gemini_chat.gemini_api.HAS_SQLITE_STORE", False):
            client = GeminiClient(api_key="test-key")
            
            client.register_tool_handler("search", lambda q: f"搜索: {q}")
            client.register_tool_handler("calculate", lambda expr: f"计算: {expr}")
            
            assert len(client._tool_handlers) == 2
            assert "search" in client._tool_handlers
            assert "calculate" in client._tool_handlers
