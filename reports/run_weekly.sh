#!/usr/bin/env bash
set -e
cd /root/coalbot
source venv/bin/activate
python3 /root/coalbot/reports/weekly_report.py | python3 /root/coalbot/reports/send_telegram.py
