#!/usr/bin/env bash
# 监控手机 embedding 服务器的内存占用，用于事后分析长期稳定性。
#
# 用法:
#   ./scripts/monitor_phone_mem.sh              # 默认 8 小时，每 60 秒采样
#   DURATION=3600 INTERVAL=30 ./scripts/monitor_phone_mem.sh
#
# 输出: logs/phone_mem_<时间戳>.raw（制表符分隔，便于后续分析）
# 字段: epoch  MemAvail_kB  MemFree_kB  SwapFree_kB  llamaRSS_kB

set -uo pipefail

INTERVAL="${INTERVAL:-60}"
DURATION="${DURATION:-28800}"
OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/logs"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/phone_mem_$(date +%Y%m%d_%H%M%S).raw"

if ! command -v adb >/dev/null 2>&1; then
  echo "错误: 未找到 adb" >&2; exit 1
fi

SAMPLES=$(( DURATION / INTERVAL ))
echo "手机内存监控启动"
echo "  设备   : $(adb shell getprop ro.product.model 2>/dev/null | tr -d '\r')"
echo "  总内存 : $(adb shell grep MemTotal /proc/meminfo | tr -dc '0-9' | awk '{printf "%.1f GB", $1/1048576}')"
echo "  采样   : $SAMPLES 次 × ${INTERVAL}s = $(($DURATION/60)) 分钟"
echo "  输出   : $OUT"
echo "  Ctrl-C 结束"
echo

printf 'epoch\tMemAvail_kB\tMemFree_kB\tSwapFree_kB\tllamaRSS_kB\n' > "$OUT"

i=0
while [ "$i" -lt "$SAMPLES" ]; do
  line=$(adb shell "echo \$(grep MemAvailable /proc/meminfo | tr -dc '0-9') \$(grep MemFree /proc/meminfo | tr -dc '0-9') \$(grep SwapFree /proc/meminfo | tr -dc '0-9') \$(ps -A -o RSS,NAME | grep llama | tr -dc '0-9')" 2>/dev/null | tr -d '\r')
  ts=$(date +%s)
  if [ -n "$line" ] && [ "$(echo "$line" | wc -w)" -ge 4 ]; then
    printf '%s\t%s\n' "$ts" "$(echo "$line" | tr ' ' '\t')" >> "$OUT"
    if [ $((i % 10)) -eq 0 ]; then
      rss=$(echo "$line" | awk '{printf "%.0f", $4/1024}')
      avail=$(echo "$line" | awk '{printf "%.0f", $1/1024}')
      printf '[%4d/%d] MemAvail %6s MB   llamaRSS %6s MB\n' "$i" "$SAMPLES" "$avail" "$rss"
    fi
  else
    echo "[warn] 第 $i 次采样失败（设备可能断开或服务未运行）"
  fi
  i=$((i+1))
  sleep "$INTERVAL"
done

echo
echo "监控结束: $OUT"
echo "分析命令:"
echo "  awk 'NR>1{if(\$4>max)max=\$4; s+=\$4; n++} END{printf \"llamaRSS 平均 %.0f MB 峰值 %.0f MB\\n\", s/n/1024, max/1024}' $OUT"