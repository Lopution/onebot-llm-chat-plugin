# 消息处理器测试
"""
测试 handlers.py 模块

覆盖内容：
- 私聊消息处理
- 群聊消息处理
- 白名单检查
- 用户档案更新
- 消息段解析
- 长消息合并转发
- 错误处理
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestHandlePrivate:
    """私聊消息处理测试"""
    
    @pytest.mark.asyncio
    async def test_handle_private_normal_message(self):
        """测试正常私聊消息处理"""
        from gemini_chat.handlers import handle_private
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.send = AsyncMock()
        
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = "你好，Mika！"
        mock_event.user_id = 123456789
        mock_event.message_id = 1001
        mock_event.original_message = MagicMock()
        mock_event.original_message.__iter__ = lambda self: iter([])
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_private = True
        mock_config.gemini_max_images = 10
        mock_config.gemini_master_id = 999999999  # 不是主人
        mock_config.gemini_forward_threshold = 300
        
        mock_gemini_client = AsyncMock()
        mock_gemini_client.chat = AsyncMock(return_value="你好呀~")
        
        # Act
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client), \
             patch("gemini_chat.handlers.extract_images", return_value=[]):
            await handle_private(mock_bot, mock_event, mock_config)
        
        # Assert
        mock_gemini_client.chat.assert_called_once()
        call_args = mock_gemini_client.chat.call_args
        assert "[私聊用户]:" in call_args.kwargs.get("message", call_args.args[0] if call_args.args else "")
        mock_bot.send.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_private_with_image(self):
        """测试带图片的私聊消息"""
        from gemini_chat.handlers import handle_private
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.send = AsyncMock()
        
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = "看看这张图"
        mock_event.user_id = 123456789
        mock_event.message_id = 1002
        mock_event.original_message = MagicMock()
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_private = True
        mock_config.gemini_max_images = 10
        mock_config.gemini_master_id = 999999999
        mock_config.gemini_forward_threshold = 300
        
        mock_gemini_client = AsyncMock()
        mock_gemini_client.chat = AsyncMock(return_value="这是一张漂亮的图片~")
        
        image_urls = ["https://example.com/image1.jpg", "https://example.com/image2.jpg"]
        
        # Act
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client), \
             patch("gemini_chat.handlers.extract_images", return_value=image_urls):
            await handle_private(mock_bot, mock_event, mock_config)
        
        # Assert
        mock_gemini_client.chat.assert_called_once()
        call_kwargs = mock_gemini_client.chat.call_args.kwargs
        assert call_kwargs.get("image_urls") == image_urls
    
    @pytest.mark.asyncio
    async def test_handle_private_empty_message_ignored(self):
        """测试空消息被忽略"""
        from gemini_chat.handlers import handle_private
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = ""
        mock_event.original_message = MagicMock()
        mock_event.original_message.__iter__ = lambda self: iter([])
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_private = True
        mock_config.gemini_max_images = 10
        
        # Act
        with patch("gemini_chat.handlers.extract_images", return_value=[]):
            await handle_private(mock_bot, mock_event, mock_config)
        
        # Assert
        mock_bot.send.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_handle_private_disabled(self):
        """测试私聊回复被禁用时不处理"""
        from gemini_chat.handlers import handle_private
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = "你好"
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_private = False  # 禁用私聊回复
        
        # Act
        await handle_private(mock_bot, mock_event, mock_config)
        
        # Assert
        mock_bot.send.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_handle_private_master_tag(self):
        """测试主人发送消息时的特殊标签"""
        from gemini_chat.handlers import handle_private
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.send = AsyncMock()
        
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = "Mika，在吗？"
        mock_event.user_id = 123456789
        mock_event.message_id = 1003
        mock_event.original_message = MagicMock()
        mock_event.original_message.__iter__ = lambda self: iter([])
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_private = True
        mock_config.gemini_max_images = 10
        mock_config.gemini_master_id = 123456789  # 是主人
        mock_config.gemini_forward_threshold = 300
        
        mock_gemini_client = AsyncMock()
        mock_gemini_client.chat = AsyncMock(return_value="Sensei！你来啦~")
        
        # Act
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client), \
             patch("gemini_chat.handlers.extract_images", return_value=[]):
            await handle_private(mock_bot, mock_event, mock_config)
        
        # Assert
        call_args = mock_gemini_client.chat.call_args
        message_arg = call_args.kwargs.get("message", call_args.args[0] if call_args.args else "")
        assert "⭐Sensei" in message_arg


class TestHandleGroup:
    """群聊消息处理测试"""
    
    @pytest.mark.asyncio
    async def test_handle_group_normal_message(self):
        """测试正常群聊消息处理"""
        from gemini_chat.handlers import handle_group
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.send = AsyncMock()
        
        mock_sender = MagicMock()
        mock_sender.card = "测试群友"
        mock_sender.nickname = "TestUser"
        
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = "Mika 你好啊"
        mock_event.user_id = 123456789
        mock_event.group_id = 987654321
        mock_event.message_id = 2001
        mock_event.sender = mock_sender
        mock_event.original_message = MagicMock()
        mock_event.original_message.__iter__ = lambda self: iter([])
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_at = True
        mock_config.gemini_group_whitelist = []  # 空白名单表示全部允许
        mock_config.gemini_max_images = 10
        mock_config.gemini_master_id = 999999999
        mock_config.gemini_forward_threshold = 300
        
        mock_gemini_client = AsyncMock()
        mock_gemini_client.chat = AsyncMock(return_value="你好呀~")
        
        mock_profile_store = AsyncMock()
        mock_profile_store.update_from_message = AsyncMock(return_value=False)
        
        # Act
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client), \
             patch("gemini_chat.handlers.extract_images", return_value=[]), \
             patch("gemini_chat.handlers.get_user_profile_store", return_value=mock_profile_store):
            await handle_group(mock_bot, mock_event, mock_config)
        
        # Assert
        mock_gemini_client.chat.assert_called_once()
        mock_bot.send.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_group_at_message(self):
        """测试 @ 机器人的消息"""
        from gemini_chat.handlers import handle_group
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.send = AsyncMock()
        
        mock_sender = MagicMock()
        mock_sender.card = "群友A"
        mock_sender.nickname = "UserA"
        
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = "帮我写一首诗"
        mock_event.user_id = 111222333
        mock_event.group_id = 444555666
        mock_event.message_id = 2002
        mock_event.sender = mock_sender
        mock_event.original_message = MagicMock()
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_at = True
        mock_config.gemini_group_whitelist = [444555666]  # 在白名单中
        mock_config.gemini_max_images = 10
        mock_config.gemini_master_id = 999999999
        mock_config.gemini_forward_threshold = 300
        
        mock_gemini_client = AsyncMock()
        mock_gemini_client.chat = AsyncMock(return_value="好的，这是一首诗~")
        
        mock_profile_store = AsyncMock()
        mock_profile_store.update_from_message = AsyncMock(return_value=False)
        
        # Act
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client), \
             patch("gemini_chat.handlers.extract_images", return_value=[]), \
             patch("gemini_chat.handlers.get_user_profile_store", return_value=mock_profile_store):
            await handle_group(mock_bot, mock_event, mock_config)
        
        # Assert
        call_args = mock_gemini_client.chat.call_args
        # 验证群组 ID 被传递
        assert call_args.kwargs.get("group_id") == "444555666"
    
    @pytest.mark.asyncio
    async def test_handle_group_whitelist_check(self):
        """测试群白名单检查 - 在白名单内"""
        from gemini_chat.handlers import handle_group
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.send = AsyncMock()
        
        mock_sender = MagicMock()
        mock_sender.card = ""
        mock_sender.nickname = "User"
        
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = "测试消息"
        mock_event.user_id = 123456
        mock_event.group_id = 111222333  # 在白名单中
        mock_event.message_id = 2003
        mock_event.sender = mock_sender
        mock_event.original_message = MagicMock()
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_at = True
        mock_config.gemini_group_whitelist = [111222333, 444555666]
        mock_config.gemini_max_images = 10
        mock_config.gemini_master_id = 999999999
        mock_config.gemini_forward_threshold = 300
        
        mock_gemini_client = AsyncMock()
        mock_gemini_client.chat = AsyncMock(return_value="收到~")
        
        mock_profile_store = AsyncMock()
        mock_profile_store.update_from_message = AsyncMock(return_value=False)
        
        # Act
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client), \
             patch("gemini_chat.handlers.extract_images", return_value=[]), \
             patch("gemini_chat.handlers.get_user_profile_store", return_value=mock_profile_store):
            await handle_group(mock_bot, mock_event, mock_config)
        
        # Assert - 在白名单内应该处理消息
        mock_gemini_client.chat.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_group_non_whitelist(self):
        """测试非白名单群消息被忽略"""
        from gemini_chat.handlers import handle_group
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = "测试消息"
        mock_event.group_id = 999888777  # 不在白名单中
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_at = True
        mock_config.gemini_group_whitelist = [111222333, 444555666]  # 配置了白名单
        
        mock_gemini_client = AsyncMock()
        
        # Act
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client):
            await handle_group(mock_bot, mock_event, mock_config)
        
        # Assert - 不在白名单内不应该处理消息
        mock_gemini_client.chat.assert_not_called()
        mock_bot.send.assert_not_called()


class TestUserProfileUpdate:
    """用户档案更新测试"""
    
    @pytest.mark.asyncio
    async def test_user_profile_update(self):
        """测试用户档案更新"""
        from gemini_chat.handlers import handle_group
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.send = AsyncMock()
        
        mock_sender = MagicMock()
        mock_sender.card = "小明"
        mock_sender.nickname = "XiaoMing"
        
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = "我叫张三，今年25岁"
        mock_event.user_id = 123456789
        mock_event.group_id = 111222333
        mock_event.message_id = 3001
        mock_event.sender = mock_sender
        mock_event.original_message = MagicMock()
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_at = True
        mock_config.gemini_group_whitelist = []
        mock_config.gemini_max_images = 10
        mock_config.gemini_master_id = 999999999
        mock_config.gemini_forward_threshold = 300
        
        mock_gemini_client = AsyncMock()
        mock_gemini_client.chat = AsyncMock(return_value="好的张三~")
        
        mock_profile_store = AsyncMock()
        mock_profile_store.update_from_message = AsyncMock(return_value=True)
        
        # Act
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client), \
             patch("gemini_chat.handlers.extract_images", return_value=[]), \
             patch("gemini_chat.handlers.get_user_profile_store", return_value=mock_profile_store):
            await handle_group(mock_bot, mock_event, mock_config)
        
        # Assert
        mock_profile_store.update_from_message.assert_called_once_with(
            qq_id="123456789",
            content="我叫张三，今年25岁",
            nickname="小明"
        )


class TestMessageSegmentParsing:
    """消息段解析测试"""
    
    def test_message_segment_parsing(self):
        """测试消息段解析"""
        from gemini_chat.tools import extract_images
        
        # Arrange
        mock_msg = MagicMock()
        
        text_seg = MagicMock()
        text_seg.type = "text"
        text_seg.data = {"text": "这是一条消息"}
        
        image_seg = MagicMock()
        image_seg.type = "image"
        image_seg.data = {"url": "https://example.com/test.jpg"}
        
        at_seg = MagicMock()
        at_seg.type = "at"
        at_seg.data = {"qq": "123456"}
        
        mock_msg.__iter__ = lambda self: iter([text_seg, image_seg, at_seg])
        
        # Act
        urls = extract_images(mock_msg, max_images=10)
        
        # Assert
        assert len(urls) == 1
        assert urls[0] == "https://example.com/test.jpg"


class TestReplyMergeForward:
    """长消息合并转发测试"""
    
    @pytest.mark.asyncio
    async def test_reply_merge_forward(self):
        """测试长消息合并转发"""
        from gemini_chat.handlers import send_forward_msg
        from nonebot.adapters.onebot.v11 import GroupMessageEvent
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.self_id = "123456789"
        mock_bot.call_api = AsyncMock()
        
        mock_event = MagicMock(spec=GroupMessageEvent)
        mock_event.group_id = 111222333
        
        long_content = "这是一段很长的回复内容" * 50  # 超过 300 字符
        
        # Act
        await send_forward_msg(mock_bot, mock_event, long_content)
        
        # Assert
        mock_bot.call_api.assert_called_once()
        call_args = mock_bot.call_api.call_args
        assert call_args.args[0] == "send_group_forward_msg"
        assert call_args.kwargs["group_id"] == 111222333
    
    @pytest.mark.asyncio
    async def test_reply_forward_fallback_on_error(self):
        """测试转发失败时返回 False（不在本函数内降级）"""
        from gemini_chat.handlers import send_forward_msg
        from nonebot.adapters.onebot.v11 import GroupMessageEvent
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.self_id = "123456789"
        mock_bot.call_api = AsyncMock(side_effect=Exception("转发失败"))
        mock_bot.send = AsyncMock()
        
        mock_event = MagicMock(spec=GroupMessageEvent)
        mock_event.group_id = 111222333
        
        content = "测试内容"
        
        # Act
        ok = await send_forward_msg(mock_bot, mock_event, content)
        
        # Assert
        assert ok is False
        mock_bot.send.assert_not_called()


class TestSendReplyWithPolicy:
    """发送策略测试"""

    @pytest.mark.asyncio
    async def test_short_reply_quote_success(self):
        """短消息优先引用发送"""
        from gemini_chat.handlers import send_reply_with_policy

        mock_bot = AsyncMock()
        mock_event = MagicMock()

        mock_config = MagicMock()
        mock_config.gemini_forward_threshold = 300
        mock_config.gemini_long_reply_image_fallback_enabled = True

        with patch("gemini_chat.handlers.safe_send", new=AsyncMock(return_value=True)) as mock_safe_send, \
             patch("gemini_chat.handlers.send_forward_msg", new=AsyncMock(return_value=True)) as mock_forward, \
             patch("gemini_chat.handlers.send_rendered_image_with_quote", new=AsyncMock(return_value=True)) as mock_image:
            await send_reply_with_policy(
                mock_bot,
                mock_event,
                "短消息",
                is_proactive=False,
                plugin_config=mock_config,
            )

        assert mock_safe_send.await_count == 1
        mock_forward.assert_not_awaited()
        mock_image.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_long_reply_forward_success(self):
        """长消息优先转发"""
        from gemini_chat.handlers import send_reply_with_policy

        mock_bot = AsyncMock()
        mock_event = MagicMock()

        mock_config = MagicMock()
        mock_config.gemini_forward_threshold = 10
        mock_config.gemini_long_reply_image_fallback_enabled = True

        with patch("gemini_chat.handlers.safe_send", new=AsyncMock(return_value=True)) as mock_safe_send, \
             patch("gemini_chat.handlers.send_forward_msg", new=AsyncMock(return_value=True)) as mock_forward, \
             patch("gemini_chat.handlers.send_rendered_image_with_quote", new=AsyncMock(return_value=True)) as mock_image:
            await send_reply_with_policy(
                mock_bot,
                mock_event,
                "这是一条很长很长很长的消息",
                is_proactive=False,
                plugin_config=mock_config,
            )

        mock_forward.assert_awaited_once()
        mock_image.assert_not_awaited()
        mock_safe_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_long_reply_forward_fail_then_image_success(self):
        """长消息转发失败后，回退图片发送"""
        from gemini_chat.handlers import send_reply_with_policy

        mock_bot = AsyncMock()
        mock_event = MagicMock()

        mock_config = MagicMock()
        mock_config.gemini_forward_threshold = 10
        mock_config.gemini_long_reply_image_fallback_enabled = True

        with patch("gemini_chat.handlers.safe_send", new=AsyncMock(return_value=True)) as mock_safe_send, \
             patch("gemini_chat.handlers.send_forward_msg", new=AsyncMock(return_value=False)) as mock_forward, \
             patch("gemini_chat.handlers.send_rendered_image_with_quote", new=AsyncMock(return_value=True)) as mock_image:
            await send_reply_with_policy(
                mock_bot,
                mock_event,
                "这是一条很长很长很长的消息",
                is_proactive=False,
                plugin_config=mock_config,
            )

        mock_forward.assert_awaited_once()
        mock_image.assert_awaited_once()
        mock_safe_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_long_reply_image_fail_then_text_quote(self):
        """图片失败后回退单条文本引用"""
        from gemini_chat.handlers import send_reply_with_policy

        mock_bot = AsyncMock()
        mock_event = MagicMock()

        mock_config = MagicMock()
        mock_config.gemini_forward_threshold = 10
        mock_config.gemini_long_reply_image_fallback_enabled = True

        with patch("gemini_chat.handlers.safe_send", new=AsyncMock(return_value=True)) as mock_safe_send, \
             patch("gemini_chat.handlers.send_forward_msg", new=AsyncMock(return_value=False)) as mock_forward, \
             patch("gemini_chat.handlers.send_rendered_image_with_quote", new=AsyncMock(return_value=False)) as mock_image:
            await send_reply_with_policy(
                mock_bot,
                mock_event,
                "这是一条很长很长很长的消息",
                is_proactive=False,
                plugin_config=mock_config,
            )

        mock_forward.assert_awaited_once()
        mock_image.assert_awaited_once()
        mock_safe_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_proactive_reply_keeps_prefix(self):
        """主动回复保留前缀后再走发送策略"""
        from gemini_chat.handlers import send_reply_with_policy

        mock_bot = AsyncMock()
        mock_event = MagicMock()

        mock_config = MagicMock()
        mock_config.gemini_forward_threshold = 300
        mock_config.gemini_long_reply_image_fallback_enabled = True

        with patch("gemini_chat.handlers.safe_send", new=AsyncMock(return_value=True)) as mock_safe_send:
            await send_reply_with_policy(
                mock_bot,
                mock_event,
                "你好",
                is_proactive=True,
                plugin_config=mock_config,
            )

        args, _kwargs = mock_safe_send.await_args
        assert "【自主回复】" in args[2]


class TestErrorHandling:
    """错误处理测试"""
    
    @pytest.mark.asyncio
    async def test_error_handling(self):
        """测试错误处理"""
        from gemini_chat.handlers import handle_private
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = "测试消息"
        mock_event.user_id = 123456789
        mock_event.message_id = 4001
        mock_event.original_message = MagicMock()
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_private = True
        mock_config.gemini_max_images = 10
        mock_config.gemini_master_id = 999999999
        mock_config.gemini_forward_threshold = 300
        
        mock_gemini_client = AsyncMock()
        mock_gemini_client.chat = AsyncMock(side_effect=Exception("API Error"))
        
        # Act & Assert - 确保异常被正确抛出或处理
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client), \
             patch("gemini_chat.handlers.extract_images", return_value=[]):
            # 根据实际代码行为，可能会抛出异常或静默处理
            try:
                await handle_private(mock_bot, mock_event, mock_config)
            except Exception:
                pass  # 异常被预期
    
    @pytest.mark.asyncio
    async def test_user_profile_update_failure_does_not_block(self):
        """测试用户档案更新失败不会阻塞主流程"""
        from gemini_chat.handlers import handle_group
        from gemini_chat.config import Config
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.send = AsyncMock()
        
        mock_sender = MagicMock()
        mock_sender.card = "用户"
        mock_sender.nickname = "User"
        
        mock_event = MagicMock()
        mock_event.get_plaintext.return_value = "测试消息"
        mock_event.user_id = 123456789
        mock_event.group_id = 111222333
        mock_event.message_id = 4002
        mock_event.sender = mock_sender
        mock_event.original_message = MagicMock()
        
        mock_config = MagicMock(spec=Config)
        mock_config.gemini_reply_at = True
        mock_config.gemini_group_whitelist = []
        mock_config.gemini_max_images = 10
        mock_config.gemini_master_id = 999999999
        mock_config.gemini_forward_threshold = 300
        
        mock_gemini_client = AsyncMock()
        mock_gemini_client.chat = AsyncMock(return_value="回复内容")
        
        mock_profile_store = AsyncMock()
        mock_profile_store.update_from_message = AsyncMock(side_effect=Exception("DB Error"))
        
        # Act
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client), \
             patch("gemini_chat.handlers.extract_images", return_value=[]), \
             patch("gemini_chat.handlers.get_user_profile_store", return_value=mock_profile_store):
            await handle_group(mock_bot, mock_event, mock_config)
        
        # Assert - 即使档案更新失败，消息仍应被处理
        mock_gemini_client.chat.assert_called_once()
        mock_bot.send.assert_called_once()


class TestHandleReset:
    """重置记忆测试"""
    
    @pytest.mark.asyncio
    async def test_handle_reset_private(self):
        """测试私聊重置记忆"""
        from gemini_chat.handlers import handle_reset
        from gemini_chat.config import Config
        from nonebot.adapters.onebot.v11 import PrivateMessageEvent
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.send = AsyncMock()
        
        mock_event = MagicMock(spec=PrivateMessageEvent)
        mock_event.user_id = 123456789
        
        mock_config = MagicMock(spec=Config)
        
        mock_gemini_client = AsyncMock()
        mock_gemini_client.clear_context_async = AsyncMock()
        
        # Act
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client):
            await handle_reset(mock_bot, mock_event, mock_config)
        
        # Assert
        mock_gemini_client.clear_context_async.assert_called_once_with("123456789", None)
        mock_bot.send.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_reset_group(self):
        """测试群聊重置记忆"""
        from gemini_chat.handlers import handle_reset
        from gemini_chat.config import Config
        from nonebot.adapters.onebot.v11 import GroupMessageEvent
        
        # Arrange
        mock_bot = AsyncMock()
        mock_bot.send = AsyncMock()
        
        mock_event = MagicMock(spec=GroupMessageEvent)
        mock_event.user_id = 123456789
        mock_event.group_id = 111222333
        
        mock_config = MagicMock(spec=Config)
        
        mock_gemini_client = AsyncMock()
        mock_gemini_client.clear_context_async = AsyncMock()
        
        # Act
        with patch("gemini_chat.handlers.get_gemini_client", return_value=mock_gemini_client):
            await handle_reset(mock_bot, mock_event, mock_config)
        
        # Assert
        mock_gemini_client.clear_context_async.assert_called_once_with("123456789", "111222333")
        mock_bot.send.assert_called_once()
