param(
  [Parameter(Mandatory = $true)]
  [string]$DistroName,
  [int]$DelaySeconds = 45
)

$ErrorActionPreference = "Stop"

# 说明：
# - 该脚本建议配合“任务计划程序”在 Windows 开机/登录时触发。
# - 需要你的 WSL2 distro 已启用 systemd（/etc/wsl.conf: [boot] systemd=true）。
# - 以 root 启动，确保能操作 systemctl。

Start-Sleep -Seconds $DelaySeconds

& wsl.exe -d $DistroName -u root -- bash -lc "systemctl is-system-running --wait >/dev/null 2>&1 || true; systemctl start napcat.service mika-bot.service"
