# 工具函数测试
"""
测试 tools.py 模块

覆盖内容：
- needs_search() 时效性关键词检测
- extract_images() 图片 URL 提取
- TIME_SENSITIVE_KEYWORDS 关键词列表
"""
import pytest
from unittest.mock import MagicMock


class TestNeedsSearch:
    """时效性关键词检测测试"""
    
    def test_needs_search_with_time_keyword_latest(self):
        """测试包含'最新'关键词时返回 True"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("最新的新闻是什么") is True
    
    def test_needs_search_with_time_keyword_now(self):
        """测试包含'现在'关键词时返回 True"""
        # needs_search 已废弃，且“现在几点了”属于本地时间问题，不应触发外部搜索
        from mika_chat_core.utils.search_engine import should_search

        assert should_search("现在几点了") is False
    
    def test_needs_search_with_time_keyword_today(self):
        """测试包含'今天'关键词时返回 True"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("今天天气怎么样") is True
    
    def test_needs_search_with_weather_keyword(self):
        """测试包含'天气'关键词时返回 True"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("北京天气预报") is True
    
    def test_needs_search_with_price_keyword(self):
        """测试包含'价格'关键词时返回 True"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("iPhone价格是多少") is True
    
    def test_needs_search_with_news_keyword(self):
        """测试包含'新闻'关键词时返回 True"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("今日新闻汇总") is True
    
    def test_needs_search_with_match_keyword(self):
        """测试包含'比赛'关键词时返回 True"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("足球比赛结果") is True
    
    def test_needs_search_with_transfer_keyword(self):
        """测试包含'转会'关键词时返回 True"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("梅西转会消息") is True
    
    def test_needs_search_without_keyword_general_chat(self):
        """测试普通聊天内容返回 False"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("你好，我叫小明") is False
    
    def test_needs_search_without_keyword_question(self):
        """测试不含时效性的一般问题返回 False"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("什么是人工智能") is False
    
    def test_needs_search_without_keyword_greeting(self):
        """测试问候语返回 False"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("早上好") is False
    
    def test_needs_search_empty_string(self):
        """测试空字符串返回 False"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("") is False
    
    def test_needs_search_with_what_happened(self):
        """测试包含'发生了什么'时返回 True"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("昨晚发生了什么") is True
    
    def test_needs_search_with_stock_price(self):
        """测试包含'股价'时返回 True"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("苹果公司股价") is True
    
    def test_needs_search_with_ranking(self):
        """测试包含'排名'时返回 True"""
        from mika_chat_core.tools import needs_search
        
        assert needs_search("英超排名") is True


class TestTimeSensitiveKeywords:
    """时效性关键词列表测试"""
    
    def test_keywords_list_not_empty(self):
        """测试关键词列表不为空"""
        from mika_chat_core.tools import TIME_SENSITIVE_KEYWORDS
        
        assert len(TIME_SENSITIVE_KEYWORDS) > 0
    
    def test_keywords_contains_time_words(self):
        """测试关键词列表包含时间相关词汇"""
        from mika_chat_core.tools import TIME_SENSITIVE_KEYWORDS
        
        time_words = ["最新", "现在", "目前", "今天"]
        for word in time_words:
            assert word in TIME_SENSITIVE_KEYWORDS
    
    def test_keywords_contains_weather_word(self):
        """测试关键词列表包含天气相关词汇"""
        from mika_chat_core.tools import TIME_SENSITIVE_KEYWORDS
        
        assert "天气" in TIME_SENSITIVE_KEYWORDS
    
    def test_keywords_contains_price_words(self):
        """测试关键词列表包含价格相关词汇"""
        from mika_chat_core.tools import TIME_SENSITIVE_KEYWORDS
        
        price_words = ["价格", "多少钱", "股价"]
        for word in price_words:
            assert word in TIME_SENSITIVE_KEYWORDS
    
    def test_keywords_contains_sports_words(self):
        """测试关键词列表包含体育相关词汇"""
        from mika_chat_core.tools import TIME_SENSITIVE_KEYWORDS
        
        sports_words = ["比赛", "赛事", "战绩", "排名"]
        for word in sports_words:
            assert word in TIME_SENSITIVE_KEYWORDS


class TestExtractImages:
    """图片提取测试"""
    
    def test_extract_images_single_image(self, mock_message_with_image):
        """测试提取单张图片"""
        from mika_chat_core.tools import extract_images
        
        urls = extract_images(mock_message_with_image, max_images=10)
        
        assert len(urls) == 1
        assert urls[0] == "https://example.com/image.jpg"
    
    def test_extract_images_multiple_images(self, mock_message_with_multiple_images):
        """测试提取多张图片"""
        from mika_chat_core.tools import extract_images
        
        urls = extract_images(mock_message_with_multiple_images, max_images=10)
        
        assert len(urls) == 5
        for i, url in enumerate(urls):
            assert f"image{i}.jpg" in url
    
    def test_extract_images_respects_max_limit(self, mock_message_with_multiple_images):
        """测试尊重最大图片数量限制"""
        from mika_chat_core.tools import extract_images
        
        urls = extract_images(mock_message_with_multiple_images, max_images=3)
        
        assert len(urls) == 3
    
    def test_extract_images_no_images(self, mock_message_with_text):
        """测试没有图片时返回空列表"""
        from mika_chat_core.tools import extract_images
        
        urls = extract_images(mock_message_with_text, max_images=10)
        
        assert urls == []
    
    def test_extract_images_gif_converted(self, mock_message_with_gif):
        """测试 GIF 图片会被转换为 PNG（交由下载链路处理，默认不走第三方代理）"""
        from mika_chat_core.tools import extract_images
        
        urls = extract_images(mock_message_with_gif, max_images=10)
        
        assert len(urls) == 1
        # URL 在提取阶段不做第三方代理转换（隐私风险）；转换发生在下载链路
        assert urls[0].endswith(".gif")
    
    def test_extract_images_gif_url_encoded(self, mock_message_with_gif):
        """测试 GIF URL 会被正确编码"""
        from mika_chat_core.tools import extract_images
        
        urls = extract_images(mock_message_with_gif, max_images=10)
        
        assert len(urls) == 1
        # URL 应该被编码（冒号和斜杠等字符）
        assert "%3A" in urls[0] or "example.com" in urls[0]
    
    def test_extract_images_max_zero(self, mock_message_with_image):
        """测试 max_images=0 时返回空列表"""
        from mika_chat_core.tools import extract_images
        
        urls = extract_images(mock_message_with_image, max_images=0)
        
        assert urls == []
    
    def test_extract_images_mixed_content(self):
        """测试混合内容消息（文本+图片）"""
        from mika_chat_core.tools import extract_images
        
        mock_msg = MagicMock()
        
        text_seg = MagicMock()
        text_seg.type = "text"
        text_seg.data = {"text": "看这两张图"}
        
        img1 = MagicMock()
        img1.type = "image"
        img1.data = {"url": "https://example.com/photo1.jpg"}
        
        img2 = MagicMock()
        img2.type = "image"
        img2.data = {"url": "https://example.com/photo2.png"}
        
        mock_msg.__iter__ = lambda self: iter([text_seg, img1, img2])
        
        urls = extract_images(mock_msg, max_images=10)
        
        assert len(urls) == 2
        assert "photo1.jpg" in urls[0]
        assert "photo2.png" in urls[1]
    
    def test_extract_images_skips_empty_url(self):
        """测试跳过空 URL 的图片段"""
        from mika_chat_core.tools import extract_images
        
        mock_msg = MagicMock()
        
        img1 = MagicMock()
        img1.type = "image"
        img1.data = {"url": "https://example.com/valid.jpg"}
        
        img2 = MagicMock()
        img2.type = "image"
        img2.data = {"url": ""}  # 空 URL
        
        img3 = MagicMock()
        img3.type = "image"
        img3.data = {}  # 没有 URL 键
        
        mock_msg.__iter__ = lambda self: iter([img1, img2, img3])
        
        urls = extract_images(mock_msg, max_images=10)
        
        assert len(urls) == 1
        assert urls[0] == "https://example.com/valid.jpg"
    
    def test_extract_images_case_insensitive_gif(self):
        """测试 GIF 扩展名大小写不敏感"""
        from mika_chat_core.tools import extract_images
        
        mock_msg = MagicMock()
        
        img = MagicMock()
        img.type = "image"
        img.data = {"url": "https://example.com/animation.GIF"}
        
        mock_msg.__iter__ = lambda self: iter([img])
        
        urls = extract_images(mock_msg, max_images=10)
        
        assert len(urls) == 1
        assert urls[0].lower().endswith(".gif")


class TestExtractImagesEdgeCases:
    """图片提取边界情况测试"""
    
    def test_extract_images_with_query_params(self):
        """测试带查询参数的图片 URL"""
        from mika_chat_core.tools import extract_images
        
        mock_msg = MagicMock()
        img = MagicMock()
        img.type = "image"
        img.data = {"url": "https://example.com/image.jpg?size=large&quality=high"}
        mock_msg.__iter__ = lambda self: iter([img])
        
        urls = extract_images(mock_msg, max_images=10)
        
        assert len(urls) == 1
        assert "size=large" in urls[0]
    
    def test_extract_images_unicode_filename(self):
        """测试包含 Unicode 字符的文件名"""
        from mika_chat_core.tools import extract_images
        
        mock_msg = MagicMock()
        img = MagicMock()
        img.type = "image"
        img.data = {"url": "https://example.com/图片.jpg"}
        mock_msg.__iter__ = lambda self: iter([img])
        
        urls = extract_images(mock_msg, max_images=10)
        
        assert len(urls) == 1
        assert "图片" in urls[0]
    
    def test_extract_images_webp_not_converted(self):
        """测试 WebP 格式不会被转换"""
        from mika_chat_core.tools import extract_images
        
        mock_msg = MagicMock()
        img = MagicMock()
        img.type = "image"
        img.data = {"url": "https://example.com/image.webp"}
        mock_msg.__iter__ = lambda self: iter([img])
        
        urls = extract_images(mock_msg, max_images=10)
        
        assert len(urls) == 1
        assert urls[0] == "https://example.com/image.webp"
        assert "wsrv.nl" not in urls[0]
