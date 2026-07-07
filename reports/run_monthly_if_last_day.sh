#!/usr/bin/env bash
set -euo pipefail

export TZ=Asia/Shanghai

today_month="$(date +%m)"
tomorrow_month="$(date -d tomorrow +%m)"

if [ "$today_month" != "$tomorrow_month" ]; then
  echo "LAST_DAY_OK $(date '+%Y-%m-%d %H:%M:%S %Z')"
  /bin/bash /root/coalbot/reports/run_monthly.sh
else
  echo "SKIP_NOT_LAST_DAY $(date '+%Y-%m-%d %H:%M:%S %Z')"
fi
