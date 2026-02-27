#!/usr/bin/env python3
"""Mika Bot 一键初始化脚本。

目标：
- 新机器最短路径启动
- 自动创建虚拟环境、安装依赖、准备 .env
"""

from __future__ import annotations

from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT_DIR / ".venv"
ENV_PATH = ROOT_DIR / ".env"
ENV_EXAMPLE_PATH = ROOT_DIR / ".env.example"


def run_command(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT_DIR, check=True)


def read_env_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_venv() -> Path:
    if not VENV_DIR.exists():
        print("未检测到 .venv，正在创建虚拟环境...")
        run_command([sys.executable, "-m", "venv", str(VENV_DIR)])
    else:
        print("检测到现有 .venv，跳过创建。")
    python_bin = get_venv_python()
    if not python_bin.exists():
        raise RuntimeError(f"虚拟环境创建失败，找不到解释器：{python_bin}")
    return python_bin


def ensure_dependencies(python_bin: Path, skip_install: bool) -> None:
    if skip_install:
        print("已选择跳过依赖安装。")
        return
    print("正在安装依赖（这一步可能需要几十秒）...")
    run_command([str(python_bin), "-m", "pip", "install", "--upgrade", "pip"])
    run_command([str(python_bin), "-m", "pip", "install", "-r", "requirements.txt"])


def ensure_env(force: bool) -> None:
    if ENV_PATH.exists() and not force:
        print("检测到 .env，跳过生成。")
        return
    if not ENV_EXAMPLE_PATH.exists():
        raise RuntimeError("缺少 .env.example，无法自动生成 .env")
    shutil.copyfile(ENV_EXAMPLE_PATH, ENV_PATH)
    print("已生成 .env（来自 .env.example）。")


def env_has_required_values(path: Path) -> bool:
    env_map = read_env_map(path)
    api_key = str(env_map.get("LLM_API_KEY", "")).strip()
    key_list = str(env_map.get("LLM_API_KEY_LIST", "")).strip()
    master_id = str(env_map.get("MIKA_MASTER_ID", "")).strip()
    return bool((api_key or key_list) and master_id and master_id != "0")


def maybe_run_wizard(python_bin: Path, no_wizard: bool) -> None:
    if no_wizard:
        print("已选择跳过配置向导。")
        return
    if env_has_required_values(ENV_PATH):
        print(".env 已具备最小必需配置，跳过向导。")
        return
    print("检测到必需配置缺失，启动交互式配置向导...")
    run_command([str(python_bin), "scripts/config_wizard.py"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Mika Bot 一键初始化脚本")
    parser.add_argument("--skip-install", action="store_true", help="跳过依赖安装")
    parser.add_argument("--force-env", action="store_true", help="强制重新生成 .env")
    parser.add_argument("--no-wizard", action="store_true", help="不启动配置向导")
    args = parser.parse_args()

    os.chdir(ROOT_DIR)
    print("=== Mika Bot Bootstrap ===")
    print(f"项目目录: {ROOT_DIR}")

    if sys.version_info < (3, 10):
        raise RuntimeError("Python 版本过低，请使用 Python 3.10 或更高版本。")

    python_bin = ensure_venv()
    ensure_dependencies(python_bin, skip_install=args.skip_install)
    ensure_env(force=args.force_env)
    maybe_run_wizard(python_bin, no_wizard=args.no_wizard)

    print("")
    print("初始化完成。建议下一步：")
    print(f"1) 运行自检: {python_bin} scripts/doctor.py")
    print(f"2) 启动机器人: {python_bin} bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
