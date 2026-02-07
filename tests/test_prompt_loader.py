# 提示词加载器测试
"""
测试 utils/prompt_loader.py 模块

覆盖内容：
- YAML 文件加载
- 系统提示词生成
- 错误处理
- 默认值处理
"""
import pytest
from pathlib import Path
from unittest.mock import patch


class TestLoadPromptYaml:
    """YAML 提示词加载测试"""
    
    def test_load_valid_yaml(self, sample_prompt_yaml: Path, temp_prompts_dir: Path):
        """测试加载有效的 YAML 文件"""
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml("test_prompt.yaml")
            
            assert data is not None
            assert "role" in data
            assert "personality" in data
            assert data["role"]["name"] == "测试角色"
    
    def test_load_nonexistent_yaml(self, temp_prompts_dir: Path):
        """测试加载不存在的 YAML 文件返回空字典"""
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml("nonexistent.yaml")
            
            assert data == {}
    
    def test_load_invalid_yaml(self, invalid_yaml_file: Path, temp_prompts_dir: Path):
        """测试加载无效的 YAML 文件返回空字典"""
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml("invalid.yaml")
            
            assert data == {}
    
    def test_load_empty_yaml(self, temp_prompts_dir: Path):
        """测试加载空 YAML 文件"""
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml
        
        # 创建空文件
        empty_yaml = temp_prompts_dir / "empty.yaml"
        empty_yaml.write_text("", encoding="utf-8")
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml("empty.yaml")
            
            assert data == {}

    def test_load_plain_text_yaml_root(self, temp_prompts_dir: Path):
        """测试 YAML 根节点为纯文本时的兼容处理（视为 system_prompt）"""
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml

        plain_yaml = temp_prompts_dir / "plain.yaml"
        plain_yaml.write_text(
            """|-
  你是一个测试助手
  请使用简洁的方式回答
""",
            encoding="utf-8",
        )

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml("plain.yaml")

            assert isinstance(data, dict)
            assert "system_prompt" in data
            assert "你是一个测试助手" in data["system_prompt"]
    
    def test_default_filename(self, temp_prompts_dir: Path):
        """测试默认文件名 mika.yaml"""
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml
        
        # 创建默认文件
        mika_yaml = temp_prompts_dir / "mika.yaml"
        mika_yaml.write_text("role:\n  name: Mika", encoding="utf-8")
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml()
            
            assert data["role"]["name"] == "Mika"


class TestGenerateSystemPrompt:
    """系统提示词生成测试"""
    
    def test_generate_with_empty_config(self):
        """测试空配置生成默认提示词"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt
        
        prompt = generate_system_prompt({})
        
        assert prompt == "你是一个友好的AI助手"
    
    def test_generate_with_role(self):
        """测试生成包含角色信息的提示词"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt
        
        config = {
            "role": {
                "name": "测试助手",
                "name_en": "Test Assistant",
                "identity": "测试专用AI"
            }
        }
        
        prompt = generate_system_prompt(config)
        
        assert "测试助手" in prompt
        assert "Test Assistant" in prompt
        assert "测试专用AI" in prompt
    
    def test_generate_with_personality(self):
        """测试生成包含性格特征的提示词"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt
        
        config = {
            "personality": {
                "core": [
                    {"trait": "友好", "description": "对用户友好"},
                    {"trait": "专业", "description": "保持专业态度"}
                ]
            }
        }
        
        prompt = generate_system_prompt(config)
        
        assert "友好" in prompt
        assert "专业" in prompt
        assert "对用户友好" in prompt
    
    def test_generate_with_social(self):
        """测试生成包含社交信息的提示词"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt
        
        config = {
            "social": {
                "love": ["编程", "测试", "调试"],
                "friends": [
                    {"name": "Alice", "trait": "勤奋"},
                    {"name": "Bob", "trait": "聪明"}
                ]
            }
        }
        
        prompt = generate_system_prompt(config)
        
        assert "编程" in prompt
        assert "测试" in prompt
        assert "Alice" in prompt
        assert "Bob" in prompt
    
    def test_generate_with_language_style(self):
        """测试生成包含语言风格的提示词"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt
        
        config = {
            "language_style": {
                "jk_style": "使用轻松的语气",
                "expressions": ["呢", "呀", "哦"],
                "forbidden": ["使用粗话", "禁用Markdown"]
            }
        }
        
        prompt = generate_system_prompt(config)
        
        assert "轻松的语气" in prompt
        assert "呢" in prompt
        assert "呀" in prompt
        assert "使用粗话" in prompt
    
    def test_generate_with_interaction_rules(self):
        """测试生成包含交互规则的提示词"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt
        
        config = {
            "interaction_rules": {
                "group_chat": ["礼貌回复", "不打断别人"],
                "knowledge": ["使用搜索工具", "确保准确性"],
                "context": ["记住历史消息"]
            }
        }
        
        prompt = generate_system_prompt(config)
        
        assert "礼貌回复" in prompt
        assert "使用搜索工具" in prompt
        assert "记住历史消息" in prompt
    
    def test_generate_with_environment(self):
        """测试生成包含环境信息的提示词"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt
        
        config = {
            "environment": {
                "master_info": "用户是程序员"
            }
        }
        
        prompt = generate_system_prompt(config, current_date="2024年1月1日")
        
        assert "用户是程序员" in prompt
        assert "2024年1月1日" in prompt
    
    def test_generate_with_master_name_placeholder(self):
        """测试主人名称占位符替换"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt
        
        config = {
            "environment": {
                "master_info": "{master_name}是最棒的"
            }
        }
        
        prompt = generate_system_prompt(config, master_name="TestMaster")
        
        assert "TestMaster是最棒的" in prompt
        assert "{master_name}" not in prompt
    
    def test_generate_with_date_placeholder(self):
        """测试日期占位符替换"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt
        
        config = {
            "environment": {
                "master_info": "今天是{current_date}"
            }
        }
        
        prompt = generate_system_prompt(config, current_date="2024年12月31日")
        
        assert "2024年12月31日" in prompt
        assert "{current_date}" not in prompt
    
    def test_generate_with_complete_config(self, sample_prompt_yaml: Path, temp_prompts_dir: Path):
        """测试使用完整配置生成提示词"""
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml, generate_system_prompt
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            config = load_prompt_yaml("test_prompt.yaml")
            prompt = generate_system_prompt(config, master_name="Sensei", current_date="2024年1月1日")
            
            assert len(prompt) > 0
            assert "测试角色" in prompt
            assert "友好" in prompt
            assert "2024年1月1日" in prompt


class TestGetSystemPrompt:
    """获取系统提示词主函数测试"""
    
    def test_get_system_prompt_with_valid_file(self, sample_prompt_yaml: Path, temp_prompts_dir: Path):
        """测试从有效文件获取系统提示词"""
        from mika_chat_core.utils.prompt_loader import get_system_prompt
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            prompt = get_system_prompt("test_prompt.yaml")
            
            assert len(prompt) > 0
            assert "测试角色" in prompt
    
    def test_get_system_prompt_with_nonexistent_file(self, temp_prompts_dir: Path):
        """测试从不存在的文件获取提示词"""
        from mika_chat_core.utils.prompt_loader import get_system_prompt
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            prompt = get_system_prompt("nonexistent.yaml")
            
            # 应该包含默认提示词（并带有功能兜底的核心约束）
            assert "你是一个友好的AI助手" in prompt
            assert "插件运行约束" in prompt
    
    def test_get_system_prompt_with_custom_master_name(self, sample_prompt_yaml: Path, temp_prompts_dir: Path):
        """测试使用自定义主人名称"""
        from mika_chat_core.utils.prompt_loader import get_system_prompt
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            prompt = get_system_prompt("test_prompt.yaml", master_name="CustomMaster")
            
            # 如果配置中有 {master_name} 占位符，应该被替换
            assert "{master_name}" not in prompt
    
    def test_get_system_prompt_with_custom_date(self, sample_prompt_yaml: Path, temp_prompts_dir: Path):
        """测试使用自定义日期"""
        from mika_chat_core.utils.prompt_loader import get_system_prompt
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            custom_date = "2025年12月25日"
            prompt = get_system_prompt("test_prompt.yaml", current_date=custom_date)
            
            assert custom_date in prompt
    
    def test_get_system_prompt_auto_date(self, sample_prompt_yaml: Path, temp_prompts_dir: Path):
        """测试自动生成当前日期"""
        from mika_chat_core.utils.prompt_loader import get_system_prompt
        from datetime import datetime
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            prompt = get_system_prompt("test_prompt.yaml")
            
            # 应该包含某个日期格式
            # 由于是自动生成的，我们只检查年份存在
            current_year = datetime.now().year
            assert str(current_year) in prompt
    
    def test_get_system_prompt_default_params(self, sample_prompt_yaml: Path, temp_prompts_dir: Path):
        """测试使用默认参数"""
        from mika_chat_core.utils.prompt_loader import get_system_prompt
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            # 只指定文件名，其他使用默认值
            prompt = get_system_prompt("test_prompt.yaml")
            
            assert len(prompt) > 0
            assert isinstance(prompt, str)


class TestPromptLoaderEdgeCases:
    """提示词加载器边界情况测试"""
    
    def test_yaml_with_chinese_content(self, temp_prompts_dir: Path):
        """测试包含中文内容的 YAML"""
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml
        
        chinese_yaml = temp_prompts_dir / "chinese.yaml"
        chinese_yaml.write_text("""
role:
  name: "圣园未花"
  identity: "茶会主席"
personality:
  core:
    - trait: "可爱"
      description: "非常可爱的角色"
""", encoding="utf-8")
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml("chinese.yaml")
            
            assert data["role"]["name"] == "圣园未花"
            assert data["personality"]["core"][0]["trait"] == "可爱"
    
    def test_yaml_with_special_characters(self, temp_prompts_dir: Path):
        """测试包含特殊字符的 YAML"""
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml
        
        special_yaml = temp_prompts_dir / "special.yaml"
        special_yaml.write_text("""
role:
  name: "Test@#$%"
  symbols: "~!@#$%^&*()"
""", encoding="utf-8")
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml("special.yaml")
            
            assert data["role"]["name"] == "Test@#$%"
    
    def test_yaml_with_multiline_strings(self, temp_prompts_dir: Path):
        """测试包含多行字符串的 YAML"""
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml, generate_system_prompt
        
        multiline_yaml = temp_prompts_dir / "multiline.yaml"
        multiline_yaml.write_text("""
role:
  name: "Test"
  identity: |
    这是一个
    多行的
    描述
""", encoding="utf-8")
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml("multiline.yaml")
            prompt = generate_system_prompt(data)
            
            assert "多行的" in data["role"]["identity"]
    
    def test_generate_prompt_with_missing_fields(self):
        """测试配置缺少某些字段时的处理"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt
        
        # 只有部分字段的配置
        partial_config = {
            "role": {
                "name": "PartialRole"
                # 缺少 name_en 和 identity
            }
        }
        
        prompt = generate_system_prompt(partial_config)
        
        assert "PartialRole" in prompt
        # 不应该因为缺少字段而报错
        assert len(prompt) > 0
    
    def test_generate_prompt_with_empty_lists(self):
        """测试包含空列表的配置"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt
        
        config = {
            "personality": {
                "core": []
            },
            "social": {
                "love": [],
                "friends": []
            }
        }
        
        prompt = generate_system_prompt(config)
        
        # 不应该报错
        assert isinstance(prompt, str)
    
    def test_yaml_with_only_comments(self, temp_prompts_dir: Path):
        """测试只包含注释的 YAML 文件"""
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml
        
        comments_yaml = temp_prompts_dir / "comments.yaml"
        comments_yaml.write_text("""
# 这是一个注释
# 另一个注释
""", encoding="utf-8")
        
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml("comments.yaml")
            
            assert data == {}

    def test_generate_prompt_with_instructions_as_string(self):
        """测试 instructions 被写成字符串时不崩溃（兼容简写）"""
        from mika_chat_core.utils.prompt_loader import generate_system_prompt

        config = {
            "role": "Mika",
            "instructions": "请用简洁的方式回答",
        }
        prompt = generate_system_prompt(config)

        assert "Mika" in prompt
        assert "请用简洁的方式回答" in prompt

    def test_get_character_name_with_role_as_string(self, temp_prompts_dir: Path):
        """测试 role 被写成字符串时，get_character_name 仍可取到名称"""
        from mika_chat_core.utils.prompt_loader import get_character_name

        p = temp_prompts_dir / "role_str.yaml"
        p.write_text(
            """
role: "Mika"
""",
            encoding="utf-8",
        )

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            assert get_character_name("role_str.yaml") == "Mika"

    def test_load_error_messages_with_invalid_type(self, temp_prompts_dir: Path):
        """测试 error_messages 类型不正确时安全降级"""
        from mika_chat_core.utils.prompt_loader import load_error_messages

        p = temp_prompts_dir / "bad_error_messages.yaml"
        p.write_text(
            """
error_messages: "not a dict"
""",
            encoding="utf-8",
        )

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            assert load_error_messages("bad_error_messages.yaml") == {}
