# Mika Bot 启动脚本（Windows）
# 目标：新机器开箱即用（创建 venv -> 安装依赖 -> 生成 .env -> 启动）

$ErrorActionPreference = "Stop"

Write-Host "================================"
Write-Host "   Mika Bot Launcher (Windows)  "
Write-Host "================================"
Write-Host ""

# 切到脚本所在目录
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# 选择可用的 Python 命令（优先 python，其次 py -3）
$pythonCmd = "python"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $pythonCmd = "py -3"
    } else {
        throw "未找到 Python，请先安装 Python 3.10+ 并确保 python/py 在 PATH 中"
    }
}

# 1) 创建/激活虚拟环境
if (-not (Test-Path ".venv")) {
    Write-Host "[1/3] 创建虚拟环境 (.venv)..."
    Invoke-Expression "$pythonCmd -m venv .venv"
}

Write-Host "[1/3] 激活虚拟环境..."
. .\.venv\Scripts\Activate.ps1

# 2) 安装依赖
Write-Host ""
Write-Host "[2/3] 安装依赖..."
python -m pip install --upgrade pip | Out-Null
pip install -r requirements.txt

# 3) 生成 .env（若缺失）
Write-Host ""
Write-Host "[3/3] 检查环境变量文件..."
if (-not (Test-Path ".env") -and -not (Test-Path ".env.prod")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env" -Force
        Write-Host "✅ 已生成 .env（来自 .env.example）"
        Write-Host "⚠️  请先编辑 .env，至少填写："
        Write-Host "   - GEMINI_API_KEY（或 GEMINI_API_KEY_LIST）"
        Write-Host "   - GEMINI_MASTER_ID"
        Write-Host ""
        Write-Host "编辑完成后重新运行 start.ps1 即可"
        exit 0
    }
}

# 若 .env 仍是示例默认值，提前提示
if (Test-Path ".env") {
    if (Select-String -Path ".env" -Pattern '^GEMINI_MASTER_ID=0$' -Quiet) {
        Write-Host "⚠️  检测到 .env 中 GEMINI_MASTER_ID 仍为 0（示例值）"
        Write-Host "💡 请编辑 .env，设置为你的 QQ 号，例如：GEMINI_MASTER_ID=123456789"
        exit 0
    }
    if (Select-String -Path ".env" -Pattern '^GEMINI_API_KEY=\"\"$' -Quiet) {
        Write-Host "⚠️  检测到 .env 中 GEMINI_API_KEY 仍为空（示例值）"
        Write-Host "💡 请编辑 .env，填写 GEMINI_API_KEY 或 GEMINI_API_KEY_LIST"
        exit 0
    }
}

Write-Host ""
Write-Host "🚀 启动 Mika Bot..."
python bot.py
