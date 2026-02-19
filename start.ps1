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
        Write-Host "   - MIKA_API_KEY（或 MIKA_API_KEY_LIST）"
        Write-Host "   - MIKA_MASTER_ID"
        Write-Host ""
        Write-Host "编辑完成后重新运行 start.ps1 即可"
        exit 0
    }
}

# NoneBot 默认会读取 .env 与 .env.prod；这里根据实际存在的文件做“示例值提醒”。
# 优先按 .env.prod 检查，避免 .env 与 .env.prod 共存时误判。
$configCheckFile = $null
if (Test-Path ".env.prod") {
    $configCheckFile = ".env.prod"
    Write-Host "✅ 使用生产环境配置 (.env.prod)"
    $env:ENVIRONMENT = "prod"
} elseif (Test-Path ".env") {
    $configCheckFile = ".env"
    Write-Host "✅ 使用默认环境配置 (.env)"
}

if ($configCheckFile) {
    if (Select-String -Path $configCheckFile -Pattern '^MIKA_MASTER_ID=0$' -Quiet) {
        Write-Host "⚠️  检测到 $configCheckFile 中 MIKA_MASTER_ID 仍为 0（示例值）"
        Write-Host "💡 请编辑 $configCheckFile，设置为你的 QQ 号，例如：MIKA_MASTER_ID=123456789"
        exit 0
    }

    if (Select-String -Path $configCheckFile -Pattern '^MIKA_API_KEY=\"\"$' -Quiet) {
        $hasKeyList = Select-String -Path $configCheckFile -Pattern '^MIKA_API_KEY_LIST=' -Quiet
        $keyListEmpty = Select-String -Path $configCheckFile -Pattern '^MIKA_API_KEY_LIST=\[\s*\]$' -Quiet
        if (-not $hasKeyList -or $keyListEmpty) {
            Write-Host "⚠️  检测到 $configCheckFile 中 MIKA_API_KEY 仍为空（示例值）"
            Write-Host "💡 请编辑 $configCheckFile，填写 MIKA_API_KEY 或 MIKA_API_KEY_LIST"
            exit 0
        }
    }
}

Write-Host ""
Write-Host "🚀 启动 Mika Bot..."
python bot.py
