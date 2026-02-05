# 搜索引擎边界测试
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from gemini_chat.utils import search_engine as search_engine_module
from gemini_chat.utils import search_classifier as search_classifier_module

class TestSearchEngineBoundary:
    """搜索功能边界条件测试"""

    @pytest.fixture(autouse=True)
    def suppress_logging(self):
        """覆盖全局的日志抑制，允许看日志"""
        import logging
        logging.disable(logging.NOTSET)
        yield

    @pytest.fixture(autouse=True)
    async def setup_search_engine(self):
        """设置和清理"""
        self.search_engine_module = search_engine_module
        
        # 保存原始 key
        original_key = getattr(search_engine_module, "SERPER_API_KEY", "")
        
        # 设置测试 key
        search_engine_module.SERPER_API_KEY = "test-key"
        search_engine_module.clear_search_cache()
        
        yield
        
        # 恢复原始 key
        search_engine_module.SERPER_API_KEY = original_key

    @pytest.mark.asyncio
    async def test_search_injection_empty_results(self):
        """测试空搜索结果的注入处理"""
        # 模拟 HTTP 客户端
        mock_client = AsyncMock()
        mock_client.is_closed = False  # 关键修复：防止 _get_http_client 重新创建客户端
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"organic": []}
        mock_client.post = AsyncMock(return_value=mock_response)
        
        # 注入 mock client 到模块对象
        with patch.object(self.search_engine_module, "_http_client", mock_client):
            # 直接调用模块中的函数
            result = await self.search_engine_module.serper_search("empty query")
            
            # Assert
            assert result == ""

    @pytest.mark.asyncio
    async def test_search_injection_special_chars(self):
        """测试包含特殊字符的结果注入"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "organic": [
                {
                    "title": "Special {Chars} & Symbols",
                    "link": "https://example.com/test?a=1&b=2",
                    "snippet": "Snippet with {braces} and [brackets]"
                }
            ]
        }
        
        mock_client = AsyncMock()
        mock_client.is_closed = False # 关键修复
        mock_client.post = AsyncMock(return_value=mock_response)
        
        mock_config = {"result_injection": {}}
        
        with patch.object(self.search_engine_module, "load_search_prompt", return_value=mock_config):
            with patch.object(self.search_engine_module, "_http_client", mock_client):
                # Act
                result = await self.search_engine_module.serper_search("special chars")
                
                # Assert
                assert "Special {Chars} & Symbols" in result
                assert "Snippet with {braces} and [brackets]" in result

    @pytest.mark.asyncio
    async def test_search_injection_malformed_template(self):
        """测试模板格式化失败时的容错处理"""
        # 模拟加载了一个错误的模板
        bad_config = {
            "result_injection": {
                "item_template": "{invalid_key} {title}" # 缺少必需的 key 或使用了不存在的 key
            }
        }
        
        mock_client = AsyncMock()
        mock_client.is_closed = False # 关键修复
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "organic": [{"title": "Test Title", "link": "http://a.com", "snippet": "Text"}]
        }
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(self.search_engine_module, "load_search_prompt", return_value=bad_config):
            with patch.object(self.search_engine_module, "_http_client", mock_client):
                # Act
                result = await self.search_engine_module.serper_search("query")
                
                # Assert
                # 应该回退到备用格式或包含 "(格式化失败)"
                assert "Test Title" in result
                assert "(格式化失败)" in result

    @pytest.mark.asyncio
    async def test_search_injection_long_text(self):
        """测试超长文本截断"""
        long_snippet = "a" * 2000
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "organic": [{"title": "Long Text", "link": "http://a.com", "snippet": long_snippet}]
        }
        
        mock_client = AsyncMock()
        mock_client.is_closed = False # 关键修复
        mock_client.post = AsyncMock(return_value=mock_response)
        
        mock_config = {"result_injection": {}}
        
        with patch.object(self.search_engine_module, "load_search_prompt", return_value=mock_config):
            with patch.object(self.search_engine_module, "_http_client", mock_client):
                # Act
                result = await self.search_engine_module.serper_search("long query")
                
                # Assert
                assert long_snippet in result

    @pytest.mark.asyncio
    async def test_search_injection_invalid_template_section_type(self):
        """测试 result_injection 被写成非 dict 时应自动降级到默认模板"""
        bad_config = {"result_injection": "oops"}

        mock_client = AsyncMock()
        mock_client.is_closed = False
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "organic": [{"title": "Fallback Title", "link": "http://a.com", "snippet": "Fallback Snippet"}]
        }
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(self.search_engine_module, "load_search_prompt", return_value=bad_config):
            with patch.object(self.search_engine_module, "_http_client", mock_client):
                result = await self.search_engine_module.serper_search("query")
                assert "Fallback Title" in result


class TestSearchClassifierBoundary:
    """搜索分类器提示词配置边界测试"""

    def test_classify_topic_section_type_invalid(self):
        """classify_topic 非 dict 时应降级为空配置"""
        with patch.object(search_classifier_module, "load_search_prompt", return_value={"classify_topic": "bad"}):
            assert search_classifier_module._get_classify_prompt() == ""
            assert search_classifier_module._get_must_search_topics() == []

    def test_search_prompt_root_type_invalid(self):
        """search.yaml 根节点非 dict 时应降级为空配置"""
        with patch.object(search_classifier_module, "load_search_prompt", return_value="bad"):
            assert search_classifier_module._get_classify_prompt() == ""
            assert search_classifier_module._get_must_search_topics() == []
