
"""
测试文件结构和资源加载
"""

from pathlib import Path

from mika_chat_core.utils.prompt_loader import load_search_prompt

def test_search_prompt_loading():
    """验证搜索提示词是否能正确加载"""
    print("Testing search prompt loading...")
    config = load_search_prompt()
    
    assert config is not None, "Config should not be None"
    assert "classify_topic" in config, "classify_topic key missing"
    assert "template" in config["classify_topic"], "template key missing"
    assert "must_search_topics" in config["classify_topic"], "must_search_topics key missing"
    
    must_topics = config["classify_topic"]["must_search_topics"]
    assert isinstance(must_topics, list), "must_search_topics should be a list"
    assert len(must_topics) > 0, "must_search_topics should not be empty"
    
    print("✅ Search prompt loaded successfully!")
    print(f"Loaded {len(must_topics)} must-search topics.")

if __name__ == "__main__":
    test_search_prompt_loading()
