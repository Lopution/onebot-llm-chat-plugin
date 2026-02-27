#!/usr/bin/env python3
"""Mika Bot 配置向导（交互式）。

用途：
- 给新手提供最小必填配置向导
- 自动写入/补全 .env，避免手动编辑出错
"""

from __future__ import annotations

from pathlib import Path
import argparse


ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"
ENV_EXAMPLE_PATH = ROOT_DIR / ".env.example"


def load_env_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def parse_env_values(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def format_env_value(value: str) -> str:
    if value == "":
        return '""'
    if any(char in value for char in (" ", "#")):
        return f'"{value}"'
    return value


def upsert_env_values(lines: list[str], updates: dict[str, str]) -> list[str]:
    key_to_index: dict[str, int] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        key_to_index[key] = index

    for key, value in updates.items():
        new_line = f"{key}={format_env_value(value)}\n"
        if key in key_to_index:
            lines[key_to_index[key]] = new_line
        else:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] = lines[-1] + "\n"
            lines.append(new_line)
    return lines


def ask_input(prompt: str, default: str = "", required: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        raw = input(f"{prompt}{suffix}: ").strip()
        if raw:
            return raw
        if default:
            return default
        if not required:
            return ""
        print("这个值是必填项，请输入后继续。")


def normalize_whitelist(raw: str) -> str:
    if not raw.strip():
        return ""
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if not items:
        return ""
    normalized: list[str] = []
    for item in items:
        if item.isdigit():
            normalized.append(item)
        else:
            normalized.append(f'"{item}"')
    return "[" + ", ".join(normalized) + "]"


def main() -> int:
    parser = argparse.ArgumentParser(description="Mika Bot 交互式配置向导")
    parser.add_argument("--all", action="store_true", help="重新填写常用项（默认只补缺失）")
    args = parser.parse_args()

    print("=== Mika Bot 配置向导 ===")
    print("将帮助你填写最小必需配置（不会改动无关字段）")
    print("")

    if not ENV_PATH.exists():
        if ENV_EXAMPLE_PATH.exists():
            ENV_PATH.write_text(ENV_EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            print("已创建 .env（来自 .env.example）")
        else:
            ENV_PATH.write_text("", encoding="utf-8")
            print("未找到 .env.example，已创建空的 .env")

    lines = load_env_lines(ENV_PATH)
    env_values = parse_env_values(lines)

    removed_keys = {
        "MIKA_API_KEY": "LLM_API_KEY",
        "MIKA_API_KEY_LIST": "LLM_API_KEY_LIST",
        "MIKA_BASE_URL": "LLM_BASE_URL",
        "MIKA_MODEL": "LLM_MODEL",
        "MIKA_FAST_MODEL": "LLM_FAST_MODEL",
        "SERPER_API_KEY": "SEARCH_API_KEY",
        "MIKA_HISTORY_IMAGE_ENABLE_COLLAGE": "MIKA_HISTORY_COLLAGE_ENABLED",
    }
    for old_key, new_key in removed_keys.items():
        if old_key in env_values:
            print(f"❌ 检测到 .env 中仍包含已移除环境变量 {old_key}（破坏性升级）")
            print(f"💡 请删除 {old_key} 并改用 {new_key}，详见 docs/guide/upgrade.md")
            return 1

    updates: dict[str, str] = {}

    current_api_key = str(env_values.get("LLM_API_KEY", "")).strip()
    current_key_list = str(env_values.get("LLM_API_KEY_LIST", "")).strip()
    need_api = args.all or (not current_api_key and not current_key_list)
    if need_api:
        api_key = ask_input("请输入 LLM_API_KEY（单 key）", default=current_api_key, required=True)
        updates["LLM_API_KEY"] = api_key

    current_master = str(env_values.get("MIKA_MASTER_ID", "")).strip()
    need_master = args.all or (not current_master or current_master == "0")
    if need_master:
        master_id = ask_input("请输入 MIKA_MASTER_ID（你的 QQ 号）", default="" if current_master == "0" else current_master, required=True)
        updates["MIKA_MASTER_ID"] = master_id

    if args.all:
        llm_provider = ask_input("LLM_PROVIDER", default=env_values.get("LLM_PROVIDER", "openai_compat"))
        llm_base_url = ask_input(
            "LLM_BASE_URL",
            default=env_values.get("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
        )
        llm_model = ask_input("LLM_MODEL", default=env_values.get("LLM_MODEL", "gemini-3-pro-high"))
        llm_fast_model = ask_input("LLM_FAST_MODEL", default=env_values.get("LLM_FAST_MODEL", "gemini-2.5-flash-lite"))
        updates["LLM_PROVIDER"] = llm_provider
        updates["LLM_BASE_URL"] = llm_base_url
        updates["LLM_MODEL"] = llm_model
        updates["LLM_FAST_MODEL"] = llm_fast_model

        host = ask_input("HOST", default=env_values.get("HOST", "0.0.0.0"))
        port = ask_input("PORT", default=env_values.get("PORT", "8080"))
        updates["HOST"] = host
        updates["PORT"] = port

        whitelist_default = str(env_values.get("MIKA_GROUP_WHITELIST", "")).strip()
        whitelist_raw = ask_input(
            "群白名单（逗号分隔，留空=不限制）",
            default=whitelist_default,
            required=False,
        )
        normalized = normalize_whitelist(whitelist_raw)
        if normalized:
            updates["MIKA_GROUP_WHITELIST"] = normalized

    if not updates:
        print("当前 .env 已满足最小必需配置，无需修改。")
        return 0

    new_lines = upsert_env_values(lines, updates)
    ENV_PATH.write_text("".join(new_lines), encoding="utf-8")

    print("")
    print("配置已写入 .env。")
    print("下一步建议：")
    print("1) 运行自检：python scripts/doctor.py")
    print("2) 启动机器人：python bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
