import json
import os
import re
import sys
import requests

sys.path.append("/root/coalbot")

from config import TELEGRAM_BOT_TOKEN

SUBSCRIBERS_PATHS = [
    "/root/coalbot/subscribers.json",
    "/root/coalbot/data/subscribers.json",
]

def _add_chat_id(out, value):
    if value is None:
        return

    if isinstance(value, (list, tuple, set)):
        for x in value:
            _add_chat_id(out, x)
        return

    if isinstance(value, dict):
        for key in ("chat_id", "id"):
            if key in value:
                _add_chat_id(out, value.get(key))
        return

    s = str(value).strip()
    if not s:
        return

    # Поддержка env вида "123,456,-100..."
    if "," in s:
        for part in s.split(","):
            _add_chat_id(out, part)
        return

    # Не принимать служебные ключи как chat_id.
    if s.lower() in {"chat_ids", "subscribers", "users", "chats"}:
        return

    # Разрешаем числовые chat_id и channel usernames.
    if re.fullmatch(r"-?\d+", s) or s.startswith("@"):
        out.append(s)

def load_chat_ids():
    raw = []

    env_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    _add_chat_id(raw, env_chat)

    for path in SUBSCRIBERS_PATHS:
        if not os.path.exists(path):
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"SUBSCRIBERS_READ_ERROR path={path} err={repr(e)}", file=sys.stderr)
            continue

        if isinstance(data, list):
            _add_chat_id(raw, data)

        elif isinstance(data, dict):
            # Нормальный формат: {"chat_ids": [123, 456]}
            for key in ("chat_ids", "subscribers", "users", "chats"):
                if key in data:
                    _add_chat_id(raw, data.get(key))

            # Старый формат: {"123": {...}, "456": {...}}
            for k, v in data.items():
                if k in {"chat_ids", "subscribers", "users", "chats"}:
                    continue

                if isinstance(v, dict) and ("chat_id" in v or "id" in v):
                    _add_chat_id(raw, v)
                else:
                    _add_chat_id(raw, k)

    out = []
    seen = set()
    for x in raw:
        if x not in seen:
            seen.add(x)
            out.append(x)

    return out

def send_message(text: str):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not found")

    chat_ids = load_chat_ids()
    print(f"CHAT_IDS_LOADED={chat_ids}", file=sys.stderr)

    if not chat_ids:
        raise RuntimeError("No valid chat ids found in subscribers.json or TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    parts = []
    while text:
        parts.append(text[:4000])
        text = text[4000:]

    errors = {}
    sent = 0

    for chat_id in chat_ids:
        for idx, part in enumerate(parts, 1):
            try:
                r = requests.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": part,
                        "disable_web_page_preview": True
                    },
                    timeout=30
                )
                r.raise_for_status()
                sent += 1
                print(f"SENT chat_id={chat_id} part={idx}/{len(parts)} len={len(part)}", file=sys.stderr)
            except Exception as e:
                body = ""
                try:
                    body = r.text[:500]
                except Exception:
                    pass
                errors.setdefault(str(chat_id), []).append(f"{repr(e)} body={body}")
                print(f"SEND_ERROR chat_id={chat_id} err={repr(e)} body={body}", file=sys.stderr)

    if sent == 0:
        raise RuntimeError(f"Telegram send failed for all chats: {errors}")

if __name__ == "__main__":
    msg = sys.stdin.read().strip()
    if not msg:
        raise RuntimeError("No message to send")
    send_message(msg)
