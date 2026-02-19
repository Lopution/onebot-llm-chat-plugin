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
        echo -e "${YELLOW}   - MIKA_API_KEY（或 MIKA_API_KEY_LIST）${NC}"
        echo -e "${YELLOW}   - MIKA_MASTER_ID${NC}"
        echo
        echo -e "${CYAN}💡 编辑完成后重新运行本脚本即可${NC}"
        exit 0
    fi
fi

# 优先按实际运行环境做配置检查：.env.prod > .env
CONFIG_CHECK_FILE=""
CONFIG_CHECK_NAME=""
if [ -f ".env.prod" ]; then
    CONFIG_CHECK_FILE=".env.prod"
    CONFIG_CHECK_NAME=".env.prod"
elif [ -f ".env" ]; then
    CONFIG_CHECK_FILE=".env"
    CONFIG_CHECK_NAME=".env"
fi

# 若配置仍是示例默认值，提前提示，避免用户一上来看到一堆报错堆栈
if [ -n "$CONFIG_CHECK_FILE" ]; then
    if grep -q '^MIKA_MASTER_ID=0' "$CONFIG_CHECK_FILE"; then
        echo -e "${YELLOW}⚠️  检测到 ${CONFIG_CHECK_NAME} 中 MIKA_MASTER_ID 仍为 0（示例值）${NC}"
        echo -e "${CYAN}💡 请编辑 ${CONFIG_CHECK_NAME}，设置为你的 QQ 号，例如：MIKA_MASTER_ID=123456789${NC}"
        exit 0
    fi

    if grep -q '^MIKA_API_KEY=\"\"' "$CONFIG_CHECK_FILE"; then
        # 若用户未配置 key_list（或仍为空），提示先填写
        if ! grep -q '^MIKA_API_KEY_LIST=' "$CONFIG_CHECK_FILE" || grep -q '^MIKA_API_KEY_LIST=\[[[:space:]]*\]$' "$CONFIG_CHECK_FILE"; then
            echo -e "${YELLOW}⚠️  检测到 ${CONFIG_CHECK_NAME} 中 MIKA_API_KEY 仍为空（示例值）${NC}"
            echo -e "${CYAN}💡 请编辑 ${CONFIG_CHECK_NAME}，填写 MIKA_API_KEY 或 MIKA_API_KEY_LIST${NC}"
            exit 0
        fi
    fi
fi

# ========== 1. 启动/检查 NapCat Docker ==========
echo -e "${YELLOW}[1/3] 检查 NapCat QQ 客户端...${NC}"

if command -v docker &> /dev/null; then
    NAPCAT_STATUS=$(docker inspect -f '{{.State.Running}}' napcat 2>/dev/null)

    if [ "$NAPCAT_STATUS" != "true" ]; then
        echo -e "${YELLOW}🔄 启动 NapCat 容器...${NC}"
        docker start napcat 2>/dev/null || true
        sleep 3
    fi

    NAPCAT_STATUS=$(docker inspect -f '{{.State.Running}}' napcat 2>/dev/null)
    if [ "$NAPCAT_STATUS" != "true" ]; then
        echo -e "${YELLOW}⚠️  未检测到可运行的 napcat 容器，跳过 NapCat 检查（仍可先启动 Bot）${NC}"
        echo -e "${CYAN}💡 你可以稍后自行部署/启动 NapCat，再配置 OneBot 反向 WS 连接到 Bot${NC}"
        echo
    else
        echo -e "${CYAN}📱 检查 NapCat 登录状态...${NC}"

        MAX_RETRIES=3
        QR_TIMEOUT=120

        retry_count=0
        LOGIN_SUCCESS=false

        while [ $retry_count -lt $MAX_RETRIES ]; do
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

                if [ $ELAPSED -ge $QR_TIMEOUT ]; then
                    echo ""
                    echo -e "${YELLOW}⏰ 二维码等待超时 (${QR_TIMEOUT}秒)${NC}"
                    break
                fi

                NAPCAT_LOGS=$(docker logs napcat --tail 100 2>&1)

                if echo "$NAPCAT_LOGS" | grep -qE "已启动|接收 <-|OneBot11.*启动|login success|登录成功"; then
                    echo ""
                    echo -e "${GREEN}✅ NapCat 已登录成功${NC}"
                    LOGIN_SUCCESS=true
                    break 2
                fi

                if echo "$NAPCAT_LOGS" | grep -qEi "过期|expired|timeout|超时|二维码.*失效|QRCode.*invalid"; then
                    echo ""
                    echo -e "${YELLOW}⚠️  二维码已过期！${NC}"
                    break
                fi

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
                        docker logs napcat --tail 50 2>&1 | grep -A 20 "请扫描下面的二维码" | head -25
                        echo ""
                        echo -e "${CYAN}⏳ 等待扫码登录中... (剩余 ${REMAINING} 秒)${NC}"
                        echo ""
                        QR_SHOWN=true
                    else
                        if [ $((ELAPSED % 10)) -eq 0 ] && [ $ELAPSED -gt 0 ]; then
                            echo -e "${CYAN}⏳ 等待中... 剩余 ${REMAINING} 秒${NC}"
                        fi
                    fi
                    sleep 5
                else
                    echo -e "${CYAN}⏳ NapCat 正在初始化...${NC}"
                    sleep 2
                fi
            done

            retry_count=$((retry_count + 1))
        done

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

# 端口占用处理：优先自动清理“残留 Bot 进程”，避免重复启动失败
is_port_in_use() {
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"$BOT_PORT" -sTCP:LISTEN >/dev/null 2>&1
        return $?
    fi
    if command -v ss >/dev/null 2>&1; then
        ss -ltn 2>/dev/null | grep -q ":${BOT_PORT} "
        return $?
    fi
    return 1
}

collect_listener_pids() {
    if command -v lsof >/dev/null 2>&1; then
        lsof -t -nP -iTCP:"$BOT_PORT" -sTCP:LISTEN 2>/dev/null | sort -u
        return
    fi
    if command -v fuser >/dev/null 2>&1; then
        fuser -n tcp "$BOT_PORT" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u
        return
    fi
    if command -v ss >/dev/null 2>&1; then
        ss -ltnp 2>/dev/null | awk -v p=":${BOT_PORT}" '
            index($4, p) {
                if (match($0, /pid=[0-9]+/)) {
                    pid = substr($0, RSTART + 4, RLENGTH - 4)
                    print pid
                }
            }
        ' | sort -u
    fi
}

is_bot_process_pid() {
    local pid="$1"
    local cmd
    cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    echo "$cmd" | grep -Eiq '(bot\.py|nonebot|mika[_-]chat)'
}

if is_port_in_use; then
    echo -e "${YELLOW}⚠️  检测到端口 ${BOT_PORT} 已被占用，尝试清理残留 Bot 进程...${NC}"

    mapfile -t LISTENER_PIDS < <(collect_listener_pids)
    if [ "${#LISTENER_PIDS[@]}" -eq 0 ]; then
        echo -e "${RED}❌ 端口 ${BOT_PORT} 被占用，但无法识别占用进程 PID${NC}"
        echo -e "${CYAN}💡 请手动释放端口后重试${NC}"
        exit 1
    fi

    BOT_PIDS=()
    NON_BOT_PIDS=()
    for pid in "${LISTENER_PIDS[@]}"; do
        if is_bot_process_pid "$pid"; then
            BOT_PIDS+=("$pid")
        else
            NON_BOT_PIDS+=("$pid")
        fi
    done

    if [ "${#NON_BOT_PIDS[@]}" -gt 0 ]; then
        echo -e "${RED}❌ 端口 ${BOT_PORT} 被非 Bot 进程占用，为避免误杀已停止启动${NC}"
        for pid in "${NON_BOT_PIDS[@]}"; do
            cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
            echo -e "${CYAN}   - PID ${pid}: ${cmd:-<unknown>}${NC}"
        done
        echo -e "${CYAN}💡 请先手动停止以上进程，或修改 ${PORT_FILE:-.env/.env.prod} 中的 PORT${NC}"
        exit 1
    fi

    if [ "${#BOT_PIDS[@]}" -gt 0 ]; then
        echo -e "${YELLOW}🔄 发现残留 Bot 进程：${BOT_PIDS[*]}，先尝试优雅退出...${NC}"
        kill -TERM "${BOT_PIDS[@]}" 2>/dev/null || true
        sleep 2
    fi

    if is_port_in_use; then
        mapfile -t REMAINING_PIDS < <(collect_listener_pids)
        FORCE_PIDS=()
        for pid in "${REMAINING_PIDS[@]}"; do
            if is_bot_process_pid "$pid"; then
                FORCE_PIDS+=("$pid")
            fi
        done

        if [ "${#FORCE_PIDS[@]}" -gt 0 ]; then
            echo -e "${YELLOW}⚠️ 端口仍占用，强制结束残留 Bot 进程：${FORCE_PIDS[*]}${NC}"
            kill -KILL "${FORCE_PIDS[@]}" 2>/dev/null || true
            sleep 1
        fi
    fi

    if is_port_in_use; then
        echo -e "${RED}❌ 自动清理后端口 ${BOT_PORT} 仍被占用，无法启动 Bot${NC}"
        echo -e "${CYAN}💡 请手动检查端口占用后重试${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ 已释放端口 ${BOT_PORT}，继续启动${NC}"
fi

python3 bot.py
