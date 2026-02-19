# 提示词加载器测试（Prompt V2）
import pytest
from pathlib import Path
from unittest.mock import patch


class TestLoadPromptYaml:
    def test_load_valid_yaml_v2(self, sample_prompt_yaml: Path, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml("test_prompt.yaml")
            assert data["name"] == "测试角色"
            assert "character_prompt" in data
            assert "dialogue_examples" in data

    def test_load_nonexistent_yaml(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            assert load_prompt_yaml("missing.yaml") == {}

    def test_load_invalid_yaml(self, invalid_yaml_file: Path, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            assert load_prompt_yaml("invalid.yaml") == {}

    def test_load_empty_yaml(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml

        empty_yaml = temp_prompts_dir / "empty.yaml"
        empty_yaml.write_text("", encoding="utf-8")

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            assert load_prompt_yaml("empty.yaml") == {}

    def test_load_plain_text_yaml_root(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml

        plain_yaml = temp_prompts_dir / "plain.yaml"
        plain_yaml.write_text(
            """|-
  你是一个测试助手
  请使用简洁方式回答
""",
            encoding="utf-8",
        )
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml("plain.yaml")
            assert "character_prompt" in data
            assert "你是一个测试助手" in data["character_prompt"]

    def test_default_filename_is_system_yaml(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml

        system_yaml = temp_prompts_dir / "system.yaml"
        system_yaml.write_text(
            """
name: "Mika"
character_prompt: "你是 Mika"
""",
            encoding="utf-8",
        )
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            data = load_prompt_yaml()
            assert data["name"] == "Mika"

    def test_reject_symlink_escape(self, temp_prompts_dir: Path, tmp_path: Path):
        from mika_chat_core.utils.prompt_loader import load_prompt_yaml

        outside = tmp_path / "outside.yaml"
        outside.write_text("name: escaped\ncharacter_prompt: escaped", encoding="utf-8")
        escape_link = temp_prompts_dir / "escape.yaml"
        try:
            escape_link.symlink_to(outside)
        except (NotImplementedError, OSError):
            pytest.skip("symlink is not supported in current environment")

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            assert load_prompt_yaml("escape.yaml") == {}


class TestGenerateSystemPrompt:
    def test_generate_system_prompt_v2_basic(self):
        from mika_chat_core.utils.prompt_loader import generate_system_prompt

        prompt = generate_system_prompt(
            {
                "name": "测试角色",
                "character_prompt": "你是{master_name}的同伴。今天是{current_date}。",
            },
            master_name="Sensei",
            current_date="2026年02月12日",
        )
        assert "Sensei" in prompt
        assert "2026年02月12日" in prompt

    def test_get_system_prompt_with_dialogue_examples(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import get_system_prompt

        yaml_path = temp_prompts_dir / "v2_examples.yaml"
        yaml_path.write_text(
            """
name: "Mika"
character_prompt: |
  你是 Mika。
dialogue_examples:
  - scenario: "问候"
    user: "你好"
    bot: "你好呀。"
""",
            encoding="utf-8",
        )

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            prompt = get_system_prompt("v2_examples.yaml")
            assert "Dialogue Examples (Few-Shot)" in prompt
            assert "User: 你好" in prompt
            assert "Mika: 你好呀。" in prompt

    def test_get_system_prompt_dialogue_examples_use_top_level_name(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import get_system_prompt

        yaml_path = temp_prompts_dir / "v2_examples_custom_name.yaml"
        yaml_path.write_text(
            """
name: "小星野"
character_prompt: |
  你是小星野。
dialogue_examples:
  - scenario: "问候"
    user: "你好"
    bot: "你好呀。"
""",
            encoding="utf-8",
        )

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            prompt = get_system_prompt("v2_examples_custom_name.yaml")
            assert "User: 你好" in prompt
            assert "小星野: 你好呀。" in prompt
            assert "Mika: 你好呀。" not in prompt

    def test_get_system_prompt_missing_required_fields_fallback(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import get_system_prompt

        bad_yaml = temp_prompts_dir / "missing_fields.yaml"
        bad_yaml.write_text(
            """
name: "OnlyName"
""",
            encoding="utf-8",
        )
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            prompt = get_system_prompt("missing_fields.yaml")
            assert "你是一个友好的AI助手" in prompt
            assert "插件运行约束" in prompt

    def test_legacy_structured_schema_no_longer_effective(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import get_system_prompt

        legacy_yaml = temp_prompts_dir / "legacy.yaml"
        legacy_yaml.write_text(
            """
role:
  name: "旧角色"
personality:
  core:
    - trait: "旧字段"
      description: "旧描述"
""",
            encoding="utf-8",
        )
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            prompt = get_system_prompt("legacy.yaml")
            assert "你是一个友好的AI助手" in prompt
            assert "旧角色" not in prompt
            assert "旧字段" not in prompt


class TestGetSystemPromptAndName:
    def test_get_system_prompt_with_valid_file(self, sample_prompt_yaml: Path, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import get_system_prompt

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            prompt = get_system_prompt("test_prompt.yaml", master_name="CustomMaster", current_date="2025年12月25日")
            assert "你是一个测试角色" in prompt
            assert "CustomMaster" in prompt
            assert "插件运行约束" in prompt

    def test_get_system_prompt_nonexistent_file(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import get_system_prompt

        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            prompt = get_system_prompt("nonexistent.yaml")
            assert "你是一个友好的AI助手" in prompt
            assert "插件运行约束" in prompt

    def test_get_character_name_from_top_level_name(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import get_character_name

        yaml_path = temp_prompts_dir / "name_only.yaml"
        yaml_path.write_text(
            """
name: "圣园未花"
character_prompt: "你是未花。"
""",
            encoding="utf-8",
        )
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            assert get_character_name("name_only.yaml") == "圣园未花"

    def test_get_character_name_missing_name_fallback(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import get_character_name

        yaml_path = temp_prompts_dir / "legacy_role.yaml"
        yaml_path.write_text(
            """
role:
  name: "LegacyName"
character_prompt: "test"
""",
            encoding="utf-8",
        )
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            assert get_character_name("legacy_role.yaml") == "助手"

    def test_load_error_messages_with_invalid_type(self, temp_prompts_dir: Path):
        from mika_chat_core.utils.prompt_loader import load_error_messages

        bad = temp_prompts_dir / "bad_error_messages.yaml"
        bad.write_text(
            """
name: "Mika"
character_prompt: "你是Mika"
error_messages: "not a dict"
""",
            encoding="utf-8",
        )
        with patch("mika_chat_core.utils.prompt_loader.PROMPTS_DIR", temp_prompts_dir):
            assert load_error_messages("bad_error_messages.yaml") == {}
