#!/data/data/com.termux/files/usr/bin/bash
# embedding 服务器看门狗（手机端，Termux 下运行）
#
# 关键点: llama-server 的 /health 在 Vulkan 设备丢失时仍返回 200，
#         进程活着但算不动。必须发真实 embedding 请求才能发现故障。
#         （实测: 崩溃后 /health HTTP 200，而 embedding 返回 500 ErrorDeviceLost）
#
# 用法:
#   chmod +x ~/emb_watchdog.sh && nohup ~/emb_watchdog.sh > ~/emb_watchdog.log 2>&1 &
#   或在 Termux 里:  termux-wake-lock && ./emb_watchdog.sh
#
# 停止: pkill -f emb_watchdog.sh

MODEL="~/models/bge-m3-Q8_0.gguf"
PORT=8222
INTERVAL=60          # 巡检间隔（秒）
FAIL_THRESHOLD=3     # 连续失败多少次才重启
PROBE_INPUT="健康检查"  # 探针文本
MAX_RSS_MB=4200      # 平台内存实测 2911MB，超过此值也重启

LOG=~/emb_watchdog.log

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

health_probe() {
  local body='{"model":"'"$MODEL"'","input":"'"$PROBE_INPUT"'"}'
  local resp
  resp=$(curl -sS -m 30 -X POST "http://127.0.0.1:$PORT/v1/embeddings" \
         -H "Content-Type: application/json" -d "$body" 2>&1)
  # 必须同时满足：HTTP 成功 + 返回合法向量长度
  if echo "$resp" | grep -q '"embedding"'; then
    return 0
  fi
  log "探针失败: $(echo "$resp" | head -c 200)"
  return 1
}

rss_mb() {
  local kb
  kb=$(ps -A -o RSS,NAME 2>/dev/null | grep llama | tr -dc '0-9')
  [ -z "$kb" ] && { echo 0; return; }
  echo $(( kb / 1024 ))
}

start_server() {
  log "启动 llama-server..."
  # -ub 5000 为实测安全上限（6200 会导致 Vulkan 设备丢失）
  nohup llama-server \
    -m "$MODEL" \
    --embeddings --pooling cls \
    -c 8192 -b 5000 -ub 5000 \
    -np 1 -ngl 99 -fa on --embd-normalize 2 \
    -ctk q8_0 -ctv q8_0 --cache-ram 0 \
    --host 0.0.0.0 --port "$PORT" \
    >> ~/llama_server.log 2>&1 &
  log "已拉起进程，等待就绪..."
}

wait_ready() {
  for _ in $(seq 1 30); do
    sleep 5
    if health_probe; then log "就绪"; return 0; fi
  done
  return 1
}

log "=== 看门狗启动 === pid=$$ interval=${INTERVAL}s threshold=$FAIL_THRESHOLD"

fails=0
restarts=0
while true; do
  sleep "$INTERVAL"

  if ! pgrep -f llama-server >/dev/null 2>&1; then
    log "检测到进程不存在，尝试拉起"
    start_server; wait_ready && restarts=$((restarts+1))
    fails=0
    continue
  fi

  rss=$(rss_mb)
  if [ "$rss" -gt "$MAX_RSS_MB" ]; then
    log "内存超限 RSS=${rss}MB > ${MAX_RSS_MB}MB，重启"
    pkill -f llama-server; sleep 5
    start_server; wait_ready && restarts=$((restarts+1))
    fails=0
    continue
  fi

  if health_probe; then
    [ "$fails" -gt 0 ] && log "恢复 (RSS=${rss}MB)"
    fails=0
  else
    fails=$((fails+1))
    log "探针连续失败 $fails/$FAIL_THRESHOLD (RSS=${rss}MB)"
    if [ "$fails" -ge "$FAIL_THRESHOLD" ]; then
      log "判定服务失效，执行重启"
      pkill -f llama-server; sleep 5
      start_server
      if wait_ready; then
        restarts=$((restarts+1))
        log "重启成功 (累计 $restarts 次)"
      else
        log "重启后仍未就绪，等待下一轮"
      fi
      fails=0
    fi
  fi
done