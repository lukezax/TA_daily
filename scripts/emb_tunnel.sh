#!/usr/bin/env bash
# embedding 服务器 SSH 隧道看门狗
#
# 为什么需要隧道：embedding 服务器 172.16.101.131 不在本机所在的 tailnet 里，
# 也没有任何节点通告子网路由，所以只能经同网段的 raco@100.82.103.73 跳。
# 裸 `ssh -f -N` 断线不会自愈，故用 cron 每分钟探一次。
#
# 探活为什么不只用 /health：llama-server 的 /health 在模型没加载/后端挂掉时
# 仍可能返回 200（手机端就踩过这个坑：/health 200 而 embedding 500）。
# 这里额外打一次 /tokenize —— 它很便宜（不跑模型），但能证明模型确实加载着。
#
# 用法:
#   ./scripts/emb_tunnel.sh            # 检查并按需重连（cron 每分钟调）
#   ./scripts/emb_tunnel.sh --status   # 只看状态，不动作
#
# 端口映射: localhost:18222 -> 172.16.101.131:8222 (短文本, ubatch 1024)
#           localhost:18223 -> 172.16.101.131:8223 (长文本, ubatch 3000)
set -u

JUMP="raco@100.82.103.73"
TARGET="172.16.101.131"
LOCAL_SHORT=18222
LOCAL_LONG=18223
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$ROOT/logs/emb_tunnel.log"
STATE="$ROOT/logs/.emb_tunnel_state"
MARKER="-L ${LOCAL_SHORT}:${TARGET}:8222"

mkdir -p "$ROOT/logs"

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

tunnel_pid() { pgrep -f "ssh.*${MARKER}" | head -1; }

# 长文本端口是主用路径，它通就够了；短文本端口顺带记录
probe() {
    local port="$1"
    curl -s -m 8 "http://localhost:${port}/health" 2>/dev/null | grep -q '"ok"' || return 1
    curl -s -m 15 -X POST "http://localhost:${port}/tokenize" \
        -H 'Content-Type: application/json' -d '{"content":"探活"}' 2>/dev/null \
        | grep -q '"tokens"' || return 1
    return 0
}

healthy() { probe "$LOCAL_LONG"; }

status() {
    local pid; pid="$(tunnel_pid)"
    if [ -z "$pid" ]; then echo "隧道进程: 无"; else echo "隧道进程: PID $pid"; fi
    if healthy; then
        echo "长文本端口 localhost:${LOCAL_LONG}: 健康（/health + /tokenize 均通过）"
    else
        echo "长文本端口 localhost:${LOCAL_LONG}: 不健康"
    fi
    if probe "$LOCAL_SHORT"; then
        echo "短文本端口 localhost:${LOCAL_SHORT}: 健康"
    else
        echo "短文本端口 localhost:${LOCAL_SHORT}: 不健康"
    fi
}

start_tunnel() {
    ssh -f -N \
        -o BatchMode=yes \
        -o StrictHostKeyChecking=accept-new \
        -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -L "${LOCAL_SHORT}:${TARGET}:8222" \
        -L "${LOCAL_LONG}:${TARGET}:8223" \
        "$JUMP"
}

if [ "${1:-}" = "--status" ]; then
    status
    exit 0
fi

if healthy; then
    # 只在「从坏变好」时记一条，避免每分钟刷日志
    if [ "$(cat "$STATE" 2>/dev/null)" != "up" ]; then
        log "✅ 隧道健康（PID $(tunnel_pid)）"
        echo up > "$STATE"
    fi
    exit 0
fi

pid="$(tunnel_pid)"
log "⚠️ 探活失败（localhost:${LOCAL_LONG}），旧隧道 PID=${pid:-无} → 重建"
if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null
    sleep 2
    kill -9 "$pid" 2>/dev/null
fi

if start_tunnel; then
    sleep 3
    if healthy; then
        log "✅ 隧道已重建（PID $(tunnel_pid)）"
        echo up > "$STATE"
        exit 0
    fi
    log "❌ 隧道进程起来了但探活仍失败 —— 多半是远端 llama-server 挂了，需要人工处理"
else
    log "❌ 无法建立隧道（跳板机 $JUMP 不可达？密钥失效？）"
fi
echo down > "$STATE"
exit 1
