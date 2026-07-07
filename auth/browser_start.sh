#!/usr/bin/env bash
set -u

BASE="/root/coalbot"
LOGDIR="$BASE/browser_logs"
MYSTEEL_PROFILE="$BASE/browser_profiles/mysteel_live"
SXCOAL_PROFILE="$BASE/browser_profiles/sxcoal_live"

mkdir -p "$LOGDIR" "$MYSTEEL_PROFILE" "$SXCOAL_PROFILE"

echo "===== browser_start $(date '+%Y-%m-%d %H:%M:%S') ====="

CHROME_BIN="$(find /root/.cache/ms-playwright -type f \( -path '*/chrome-linux/chrome' -o -path '*/chrome-linux64/chrome' \) | head -n 1)"

if [ -z "$CHROME_BIN" ] || [ ! -x "$CHROME_BIN" ]; then
  echo "ERROR: Chrome binary not found in /root/.cache/ms-playwright"
  echo "Run: /root/coalbot/venv/bin/python -m playwright install chromium"
  exit 1
fi

echo "CHROME_BIN=$CHROME_BIN"

echo "Stopping old browser processes on ports 9222/9223..."
pkill -f "remote-debugging-port=9222" 2>/dev/null || true
pkill -f "remote-debugging-port=9223" 2>/dev/null || true

# Xvfb нужен для нормального live-browser режима.
if ! pgrep -f "Xvfb :99" >/dev/null 2>&1; then
  echo "Starting Xvfb :99..."
  nohup Xvfb :99 -screen 0 1920x1080x24 >> "$LOGDIR/xvfb.log" 2>&1 &
  sleep 2
else
  echo "Xvfb :99 already running"
fi

export DISPLAY=:99

if command -v fluxbox >/dev/null 2>&1; then
  if ! pgrep -f "fluxbox" >/dev/null 2>&1; then
    echo "Starting fluxbox..."
    nohup fluxbox >> "$LOGDIR/fluxbox.log" 2>&1 &
    sleep 1
  fi
fi

echo "Starting MYSTEEL Chrome on CDP 9222..."
nohup "$CHROME_BIN" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir="$MYSTEEL_PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-dev-shm-usage \
  --no-sandbox \
  --disable-gpu \
  --disable-background-timer-throttling \
  --disable-backgrounding-occluded-windows \
  --disable-renderer-backgrounding \
  "https://news.mysteel.com/" \
  >> "$LOGDIR/mysteel_live.log" 2>&1 &

echo "Starting SXCOAL Chrome on CDP 9223..."
nohup "$CHROME_BIN" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9223 \
  --user-data-dir="$SXCOAL_PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-dev-shm-usage \
  --no-sandbox \
  --disable-gpu \
  --disable-background-timer-throttling \
  --disable-backgrounding-occluded-windows \
  --disable-renderer-backgrounding \
  "https://www.sxcoal.com/en" \
  >> "$LOGDIR/sxcoal_live.log" 2>&1 &

echo "Waiting for CDP ports..."
ok9222=0
ok9223=0

for i in $(seq 1 20); do
  if curl -sS --max-time 2 http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
    ok9222=1
  fi
  if curl -sS --max-time 2 http://127.0.0.1:9223/json/version >/dev/null 2>&1; then
    ok9223=1
  fi

  if [ "$ok9222" = "1" ] && [ "$ok9223" = "1" ]; then
    break
  fi

  sleep 1
done

echo "MYSTEEL_CDP_9222=$ok9222"
echo "SXCOAL_CDP_9223=$ok9223"

if [ "$ok9222" != "1" ]; then
  echo "ERROR: MYSTEEL CDP 9222 did not start"
  tail -n 80 "$LOGDIR/mysteel_live.log" || true
fi

if [ "$ok9223" != "1" ]; then
  echo "ERROR: SXCOAL CDP 9223 did not start"
  tail -n 80 "$LOGDIR/sxcoal_live.log" || true
fi

if [ "$ok9222" = "1" ] && [ "$ok9223" = "1" ]; then
  echo "LIVE BROWSERS STARTED OK"
  echo "MYSTEEL: 9222"
  echo "SXCOAL: 9223"
  exit 0
fi

exit 1
