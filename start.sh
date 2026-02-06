#!/bin/bash

echo "================================"
echo "   🌸 Mika Bot 启动脚本 🌸"
echo "================================"
echo

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ========== 0. 准备环境变量文件（开箱即用） ==========
# NoneBot 默认会读取 .env 与 .env.prod；这里仅做“缺失时生成示例”的友好提示。
if [ ! -f ".env" ] && [ ! -f ".env.prod" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${GREEN}✅ 已生成 .env（来自 .env.example）${NC}"
        echo -e "${YELLOW}⚠️  请先编辑 .env，至少填写：${NC}"
        echo -e "${YELLOW}   - GEMINI_API_KEY（或 GEMINI_API_KEY_LIST）${NC}"
        echo -e "${YELLOW}   - GEMINI_MASTER_ID${NC}"
        echo
        echo -e "${CYAN}💡 编辑完成后重新运行本脚本即可${NC}"
        exit 0
    fi
fi

# 若 .env 存在但仍是示例默认值，提前提示，避免用户一上来看到一堆报错堆栈
if [ -f ".env" ]; then
    if grep -q '^GEMINI_MASTER_ID=0' ".env"; then
        echo -e "${YELLOW}⚠️  检测到 .env 中 GEMINI_MASTER_ID 仍为 0（示例值）${NC}"
        echo -e "${CYAN}💡 请编辑 .env，设置为你的 QQ 号，例如：GEMINI_MASTER_ID=123456789${NC}"
        exit 0
    fi

    if grep -q '^GEMINI_API_KEY=\"\"' ".env"; then
        # 若用户未配置 key_list（或仍为空），提示先填写
        if ! grep -q '^GEMINI_API_KEY_LIST=' ".env" || grep -q '^GEMINI_API_KEY_LIST=\\[\\s*\\]' ".env"; then
            echo -e "${YELLOW}⚠️  检测到 .env 中 GEMINI_API_KEY 仍为空（示例值）${NC}"
            echo -e "${CYAN}💡 请编辑 .env，填写 GEMINI_API_KEY 或 GEMINI_API_KEY_LIST${NC}"
            exit 0
        fi
    fi
fi

# ========== 1. 启动/检查 NapCat Docker ==========
echo -e "${YELLOW}[1/3] 检查 NapCat QQ 客户端...${NC}"

if command -v docker &> /dev/null; then
    # 检查 NapCat 容器状态
    NAPCAT_STATUS=$(docker inspect -f '{{.State.Running}}' napcat 2>/dev/null)
    
    if [ "$NAPCAT_STATUS" != "true" ]; then
        echo -e "${YELLOW}🔄 启动 NapCat 容器...${NC}"
        docker start napcat 2>/dev/null || true
        sleep 3
    fi

    # 再次确认容器是否可用；不可用则跳过 NapCat 检查，继续启动 Bot
    NAPCAT_STATUS=$(docker inspect -f '{{.State.Running}}' napcat 2>/dev/null)
    if [ "$NAPCAT_STATUS" != "true" ]; then
        echo -e "${YELLOW}⚠️  未检测到可运行的 napcat 容器，跳过 NapCat 检查（仍可先启动 Bot）${NC}"
        echo -e "${CYAN}💡 你可以稍后自行部署/启动 NapCat，再配置 OneBot 反向 WS 连接到 Bot${NC}"
        echo
        LOGIN_SUCCESS=false
    else
    
        # 检查 NapCat 登录状态（带二维码过期自动刷新功能）
        echo -e "${CYAN}📱 检查 NapCat 登录状态...${NC}"
    
        # 配置参数
        MAX_RETRIES=3          # 最大重试次数
        QR_TIMEOUT=120         # 每个二维码等待时间（秒）
    
        retry_count=0
        LOGIN_SUCCESS=false
    
        while [ $retry_count -lt $MAX_RETRIES ]; do
            # 如果不是第一次尝试，需要重启容器刷新二维码
            if [ $retry_count -gt 0 ]; then
                echo ""
                echo -e "${YELLOW}🔄 重启 NapCat 容器获取新二维码... (尝试 $((retry_count + 1))/$MAX_RETRIES)${NC}"
                docker restart napcat >/dev/null 2>&1 || true
                sleep 5
            fi
        
            QR_SHOWN=false
            START_TIME=$(date +%s)
        
            while true; do
                CURRENT_TIME=$(date +%s)
                ELAPSED=$((CURRENT_TIME - START_TIME))
                REMAINING=$((QR_TIMEOUT - ELAPSED))
            
                # 超时检查
                if [ $ELAPSED -ge $QR_TIMEOUT ]; then
                    echo ""
                    echo -e "${YELLOW}⏰ 二维码等待超时 (${QR_TIMEOUT}秒)${NC}"
                    break
                fi
            
                NAPCAT_LOGS=$(docker logs napcat --tail 100 2>&1)
            
                # 检查是否已登录成功（检测 WebSocket 启动 或 接收消息）
                if echo "$NAPCAT_LOGS" | grep -qE "已启动|接收 <-|OneBot11.*启动|login success|登录成功"; then
                    echo ""
                    echo -e "${GREEN}✅ NapCat 已登录成功${NC}"
                    LOGIN_SUCCESS=true
                    break 2  # 跳出两层循环
                fi
            
                # 检查二维码是否过期
                if echo "$NAPCAT_LOGS" | grep -qEi "过期|expired|timeout|超时|二维码.*失效|QRCode.*invalid"; then
                    echo ""
                    echo -e "${YELLOW}⚠️  二维码已过期！${NC}"
                    break  # 跳出内层循环，进入下一次重试
                fi
            
                # 检查是否需要扫码
                if echo "$NAPCAT_LOGS" | grep -q "二维码"; then
                    if [ "$QR_SHOWN" = false ]; then
                        echo ""
                        echo -e "${YELLOW}⚠️  NapCat 需要扫码登录！${NC}"
                        if [ $retry_count -gt 0 ]; then
                            echo -e "${CYAN}   (第 $((retry_count + 1)) 次尝试，共 $MAX_RETRIES 次)${NC}"
                        fi
                        echo ""
                        echo -e "${CYAN}📱 请用手机 QQ 扫描以下二维码：${NC}"
                        echo ""
                        # 直接显示 docker 日志中的二维码
                        docker logs napcat --tail 50 2>&1 | grep -A 20 "请扫描下面的二维码" | head -25
                        echo ""
                        echo -e "${CYAN}⏳ 等待扫码登录中... (剩余 ${REMAINING} 秒)${NC}"
                        echo ""
                        QR_SHOWN=true
                    else
                        # 更新剩余时间显示（每10秒更新一次）
                        if [ $((ELAPSED % 10)) -eq 0 ] && [ $ELAPSED -gt 0 ]; then
                            echo -e "${CYAN}⏳ 等待中... 剩余 ${REMAINING} 秒${NC}"
                        fi
                    fi
                    sleep 5
                else
                    # 可能还在初始化
                    echo -e "${CYAN}⏳ NapCat 正在初始化...${NC}"
                    sleep 2
                fi
            done
        
            retry_count=$((retry_count + 1))
        done
    
        # 检查最终登录状态
        if [ "$LOGIN_SUCCESS" != "true" ]; then
            echo ""
            echo -e "${YELLOW}⚠️  NapCat 登录未完成（已达到最大重试次数 $MAX_RETRIES 次）${NC}"
            echo -e "${CYAN}💡 不影响 Bot 启动，你可以稍后手动登录 NapCat：${NC}"
            echo -e "${CYAN}   docker restart napcat && docker logs -f napcat${NC}"
        fi
    fi
else
    echo -e "${YELLOW}⚠️ Docker 未安装，跳过 NapCat 检查（仍可先启动 Bot）${NC}"
fi

echo

# ========== 2. 激活虚拟环境 ==========
echo -e "${YELLOW}[2/3] 准备 Python 环境...${NC}"

if [ -d ".venv" ]; then
    echo -e "${GREEN}✅ 激活虚拟环境${NC}"
    source .venv/bin/activate
else
    echo -e "${YELLOW}⚠️ 未找到虚拟环境，使用系统 Python${NC}"
fi

# 检查环境配置
if [ -f ".env.prod" ]; then
    echo -e "${GREEN}✅ 使用生产环境配置 (.env.prod)${NC}"
    export ENVIRONMENT=prod
elif [ -f ".env" ]; then
    echo -e "${GREEN}✅ 使用默认环境配置 (.env)${NC}"
fi

echo

# ========== 3. 启动 Bot ==========
echo -e "${YELLOW}[3/3] 启动 Mika Bot...${NC}"
echo "================================"
echo

# 从 .env/.env.prod 读取 PORT（不 source，避免 JSON 数组等语法导致报错）
BOT_PORT="8080"
PORT_FILE=""
if [ "${ENVIRONMENT:-}" = "prod" ] && [ -f ".env.prod" ]; then
    # 生产模式优先读取 .env.prod，避免 .env 并存时端口判断偏差
    PORT_FILE=".env.prod"
elif [ -f ".env" ]; then
    PORT_FILE=".env"
elif [ -f ".env.prod" ]; then
    PORT_FILE=".env.prod"
fi
if [ -n "$PORT_FILE" ]; then
    port_line="$(grep -E '^PORT=' "$PORT_FILE" 2>/dev/null | tail -n 1 || true)"
    if [ -n "$port_line" ]; then
        port_val="$(echo "$port_line" | cut -d= -f2- | tr -d '\"' | tr -d '\r' | xargs || true)"
        if echo "$port_val" | grep -qE '^[0-9]+$'; then
            BOT_PORT="$port_val"
        fi
    fi
fi

# 防止重复启动：若端口已占用，则优先重启 systemd 服务；否则尝试停止旧进程后再启动
PORT_IN_USE=false
if command -v ss &> /dev/null; then
    if ss -ltn 2>/dev/null | grep -q ":${BOT_PORT} "; then
        PORT_IN_USE=true
    fi
elif command -v lsof &> /dev/null; then
    if lsof -nP -iTCP:${BOT_PORT} -sTCP:LISTEN >/dev/null 2>&1; then
        PORT_IN_USE=true
    fi
fi

if [ "$PORT_IN_USE" = true ]; then
    echo -e "${YELLOW}⚠️  端口 ${BOT_PORT} 已被占用，尝试停止/重启现有实例...${NC}"

    # 1) 若已启用 systemd 服务，直接重启服务（更符合长期运行场景）
    if command -v systemctl &> /dev/null; then
        if systemctl is-active --quiet mika-bot.service 2>/dev/null; then
            echo -e "${CYAN}🔄 检测到 mika-bot.service 正在运行，重启服务...${NC}"
            systemctl restart mika-bot.service 2>/dev/null || {
                echo -e "${RED}❌ systemd 重启失败，将尝试手动停止占用端口的进程${NC}"
            }
            # 重启成功则进入日志跟踪模式，避免再启动一个前台实例
            if systemctl is-active --quiet mika-bot.service 2>/dev/null; then
                echo -e "${GREEN}✅ 已重启 mika-bot.service${NC}"
                echo -e "${CYAN}📋 进入日志跟踪模式（按 Ctrl+C 退出）: journalctl -u mika-bot.service -f -o cat${NC}"
                echo
                if command -v journalctl &> /dev/null; then
                    # journalctl 输出通常不带颜色，这里做简单的基于关键字的高亮，便于观察
                    journalctl -u mika-bot.service -f -o cat | awk -v RED="$RED" -v GREEN="$GREEN" -v YELLOW="$YELLOW" -v CYAN="$CYAN" -v NC="$NC" '
                        {
                            line = $0
                            if (line ~ /\[ERROR\]/) { print RED line NC; fflush(); next }
                            if (line ~ /\[WARNING\]/) { print YELLOW line NC; fflush(); next }
                            if (line ~ /\[SUCCESS\]/) { print GREEN line NC; fflush(); next }
                            if (line ~ /\[INFO\]/) { print CYAN line NC; fflush(); next }
                            print line
                            fflush()
                        }
                    '
                else
                    echo -e "${YELLOW}⚠️ journalctl 不可用，无法跟踪 systemd 日志${NC}"
                fi
                exit 0
            fi
        fi
    fi

    # 2) 兜底：尝试停止占用端口的旧进程（仅在确认是本项目进程时才会停止）
    PIDS=""
    if command -v lsof &> /dev/null; then
        PIDS="$(lsof -t -nP -iTCP:${BOT_PORT} -sTCP:LISTEN 2>/dev/null || true)"
    fi
    if [ -z "$PIDS" ] && command -v ss &> /dev/null; then
        PIDS="$(ss -ltnp 2>/dev/null | awk -v port=":${BOT_PORT} " '$0 ~ port {match($0, /pid=([0-9]+)/, m); if (m[1]) print m[1]}' | sort -u)"
    fi

    if [ -n "$PIDS" ]; then
        for pid in $PIDS; do
            cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
            cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"

            # 仅停止“看起来就是 Mika Bot”的进程：在项目目录启动，或命令行包含 bot.py
            if [ "$cwd" = "$SCRIPT_DIR" ] || echo "$cmd" | grep -q "bot.py"; then
                echo -e "${CYAN}🛑 停止旧进程 PID=$pid${NC}"
                kill "$pid" 2>/dev/null || true
                sleep 1

                # 若仍未退出，强制 kill
                if ps -p "$pid" >/dev/null 2>&1; then
                    echo -e "${YELLOW}⚠️  旧进程仍在运行，强制结束 PID=$pid${NC}"
                    kill -9 "$pid" 2>/dev/null || true
                fi
            else
                echo -e "${RED}❌ 端口 ${BOT_PORT} 被未知进程占用，脚本不会自动终止它${NC}"
                echo -e "${YELLOW}   PID: $pid${NC}"
                echo -e "${YELLOW}   CMD: $cmd${NC}"
                echo -e "${YELLOW}   CWD: ${cwd:-unknown}${NC}"
                echo -e "${CYAN}💡 请你手动释放端口后再运行该脚本${NC}"
                exit 1
            fi
        done
    fi
fi

# 优先使用 systemd 服务启动（长期运行 + 自动重启 + 统一环境），并进入日志跟踪模式
if command -v systemctl &> /dev/null; then
    if systemctl status mika-bot.service >/dev/null 2>&1; then
        if systemctl is-active --quiet mika-bot.service 2>/dev/null; then
            echo -e "${CYAN}🔄 重启 mika-bot.service...${NC}"
            systemctl restart mika-bot.service 2>/dev/null || {
                echo -e "${RED}❌ systemd 重启失败，将改为前台启动 bot.py${NC}"
            }
        else
            echo -e "${CYAN}🚀 启动 mika-bot.service...${NC}"
            systemctl start mika-bot.service 2>/dev/null || {
                echo -e "${RED}❌ systemd 启动失败，将改为前台启动 bot.py${NC}"
            }
        fi

        if systemctl is-active --quiet mika-bot.service 2>/dev/null; then
            echo -e "${GREEN}✅ mika-bot.service 已运行${NC}"
            echo -e "${CYAN}📋 进入日志跟踪模式（按 Ctrl+C 退出）: journalctl -u mika-bot.service -f -o cat${NC}"
            echo
            if command -v journalctl &> /dev/null; then
                journalctl -u mika-bot.service -f -o cat | awk -v RED="$RED" -v GREEN="$GREEN" -v YELLOW="$YELLOW" -v CYAN="$CYAN" -v NC="$NC" '
                    {
                        line = $0
                        if (line ~ /\[ERROR\]/) { print RED line NC; fflush(); next }
                        if (line ~ /\[WARNING\]/) { print YELLOW line NC; fflush(); next }
                        if (line ~ /\[SUCCESS\]/) { print GREEN line NC; fflush(); next }
                        if (line ~ /\[INFO\]/) { print CYAN line NC; fflush(); next }
                        print line
                        fflush()
                    }
                '
            else
                echo -e "${YELLOW}⚠️ journalctl 不可用，无法跟踪 systemd 日志${NC}"
            fi
            exit 0
        fi
    fi
fi

python3 bot.py
