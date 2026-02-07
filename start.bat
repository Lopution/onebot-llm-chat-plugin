@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Mika Bot Launcher

echo ================================
echo    Mika Bot Launcher
echo ================================
echo.
echo [INFO] Starting Mika Bot via WSL...
echo.

rem Check if WSL is available
wsl --status >nul 2>&1
if errorlevel 1 (
    echo [ERROR] WSL is not installed or not available.
    echo Please install WSL and at least one Linux distribution.
    pause
    exit /b 1
)

rem Pick distro:
rem 1) Use MIKA_WSL_DISTRO if user set it.
rem 2) Otherwise use default distro from `wsl -l -v` (line with leading '*').
set "DISTRO=%MIKA_WSL_DISTRO%"
if not defined DISTRO (
    for /f "tokens=2 delims= " %%D in ('wsl -l -v ^| findstr /b /c:"*"') do (
        set "DISTRO=%%D"
    )
)

if not defined DISTRO (
    echo [ERROR] Could not detect a WSL distro.
    echo Run ^`wsl -l -v^` and set one as default, or set env var MIKA_WSL_DISTRO.
    pause
    exit /b 1
)

echo [INFO] Using WSL distro: %DISTRO%

rem Pick Linux project dir:
rem 1) Use MIKA_BOT_DIR if set
rem 2) fallback: /root/bot
set "BOT_DIR=%MIKA_BOT_DIR%"
if not defined BOT_DIR (
    set "BOT_DIR=/root/bot"
)
echo [INFO] Using project dir: %BOT_DIR%

rem Run bot startup script in WSL as root
wsl.exe -d "%DISTRO%" -u root -- bash -lc "cd %BOT_DIR% && ./start.sh"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Bot exited with code %EXIT_CODE%.
    echo Tip: verify distro and path with:
    echo      wsl -l -v
    echo      wsl.exe -d "%DISTRO%" -u root -- bash -lc "ls -ld %BOT_DIR%"
    pause
)

exit /b %EXIT_CODE%
