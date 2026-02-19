#!/usr/bin/env python3
"""Mika Bot 运行前自检脚本。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import importlib.util
import socket
import sys
import urllib.request


ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    level: str
    title: str
    detail: str
    fix: str = ""


def read_env(path: Path) -> dict[str, str]:
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


def find_env_file() -> Path | None:
    candidate = ROOT_DIR / ".env"
    if candidate.exists():
        return candidate
    return None


def check_python_version() -> CheckResult:
    if sys.version_info >= (3, 10):
        return CheckResult("PASS", "Python 版本", f"{sys.version.split()[0]}")
    return CheckResult(
        "FAIL",
        "Python 版本",
        f"{sys.version.split()[0]}（需要 >= 3.10）",
        "请安装 Python 3.10+，然后重新运行。",
    )


def check_venv() -> CheckResult:
    if (ROOT_DIR / ".venv").exists():
        return CheckResult("PASS", "虚拟环境", ".venv 已存在")
    return CheckResult(
        "WARN",
        "虚拟环境",
        ".venv 不存在",
        "运行: python scripts/bootstrap.py",
    )


def check_dependencies() -> CheckResult:
    required = ["nonebot", "httpx", "pydantic"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if not missing:
        return CheckResult("PASS", "依赖检查", "核心依赖可导入")
    return CheckResult(
        "FAIL",
        "依赖检查",
        f"缺少依赖: {', '.join(missing)}",
        "运行: python scripts/bootstrap.py",
    )


def check_env() -> tuple[CheckResult, dict[str, str]]:
    env_file = find_env_file()
    if env_file is None:
        return (
            CheckResult(
                "FAIL",
                "环境文件",
                "未找到 .env",
                "运行: python scripts/bootstrap.py",
            ),
            {},
        )
    env_map = read_env(env_file)
    api_key = str(env_map.get("MIKA_API_KEY", "")).strip()
    key_list = str(env_map.get("MIKA_API_KEY_LIST", "")).strip()
    master_id = str(env_map.get("MIKA_MASTER_ID", "")).strip()
    if (api_key or key_list) and master_id and master_id != "0":
        return CheckResult("PASS", "关键配置", f"使用 {env_file.name}"), env_map
    return (
        CheckResult(
            "FAIL",
            "关键配置",
            f"{env_file.name} 缺少 MIKA_API_KEY(或 KEY_LIST) / MIKA_MASTER_ID",
            "运行: python scripts/config_wizard.py",
        ),
        env_map,
    )


def check_port(env_map: dict[str, str]) -> CheckResult:
    port = int(env_map.get("PORT", "8080") or "8080")
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        in_use = probe.connect_ex(("127.0.0.1", port)) == 0
        probe.close()
    except PermissionError:
        return CheckResult(
            "WARN",
            "端口检查",
            "当前运行环境禁止 socket 探测，已跳过",
            "在本机终端直接运行 doctor.py 可得到完整端口检查结果。",
        )
    if in_use:
        return CheckResult(
            "WARN",
            "端口检查",
            f"127.0.0.1:{port} 已被占用（如果是正在运行的 Bot 可忽略）",
            "若异常占用，停止旧进程后再启动。",
        )
    return CheckResult("PASS", "端口检查", f"127.0.0.1:{port} 可用")


def check_runtime_health(env_map: dict[str, str], enable_runtime_check: bool) -> CheckResult:
    if not enable_runtime_check:
        return CheckResult("INFO", "运行态健康检查", "已跳过（使用 --runtime 启用）")
    port = int(env_map.get("PORT", "8080") or "8080")
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status == 200:
                return CheckResult("PASS", "运行态健康检查", f"{url} 可访问")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "WARN",
            "运行态健康检查",
            f"无法访问 {url} ({exc})",
            "如果 Bot 未启动可忽略；先运行: python bot.py",
        )
    return CheckResult("WARN", "运行态健康检查", f"{url} 返回非 200")


def print_result(result: CheckResult) -> None:
    icons = {
        "PASS": "✅",
        "WARN": "⚠️",
        "FAIL": "❌",
        "INFO": "ℹ️",
    }
    icon = icons.get(result.level, "•")
    print(f"{icon} [{result.level}] {result.title}: {result.detail}")
    if result.fix:
        print(f"    修复建议: {result.fix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Mika Bot 运行前自检")
    parser.add_argument("--runtime", action="store_true", help="额外检查 /health 运行态")
    args = parser.parse_args()

    print("=== Mika Bot Doctor ===")
    print(f"项目目录: {ROOT_DIR}")
    print("")

    results: list[CheckResult] = []
    results.append(check_python_version())
    results.append(check_venv())
    results.append(check_dependencies())
    env_result, env_map = check_env()
    results.append(env_result)
    results.append(check_port(env_map))
    results.append(check_runtime_health(env_map, enable_runtime_check=args.runtime))

    has_fail = False
    for item in results:
        print_result(item)
        if item.level == "FAIL":
            has_fail = True

    print("")
    if has_fail:
        print("结论：存在阻断问题，建议先修复 FAIL 项。")
        return 1

    print("结论：可以启动。建议命令：python bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
