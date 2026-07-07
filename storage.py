
import json
import os
from typing import Any
from config import (
    DATA_DIR,
    DATA_STATE_DIR,
    STATE_FILE,
    SUBSCRIBERS_FILE,
    EVENT_MEMORY_FILE,
    CACHE_FILE,
    PRIMARY_TELEGRAM_CHAT_ID,
)


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DATA_STATE_DIR, exist_ok=True)


def save_json(path: str, obj: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_jsonl(path: str, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_state():
    return load_json(STATE_FILE, {
        "sent_slots": {},
        "last_summary_ru": "",
        "last_summary_zh": "",
    })


def save_state(state):
    save_json(STATE_FILE, state)


def load_subscribers():
    subs = load_json(SUBSCRIBERS_FILE, {"chat_ids": []})
    if PRIMARY_TELEGRAM_CHAT_ID:
        if PRIMARY_TELEGRAM_CHAT_ID not in subs["chat_ids"]:
            subs["chat_ids"].append(PRIMARY_TELEGRAM_CHAT_ID)
    return subs


def save_subscribers(subs):
    save_json(SUBSCRIBERS_FILE, subs)


def add_subscriber(chat_id: str):
    subs = load_subscribers()
    if str(chat_id) not in subs["chat_ids"]:
        subs["chat_ids"].append(str(chat_id))
        save_subscribers(subs)


def load_event_memory():
    return load_json(EVENT_MEMORY_FILE, {"events": []})


def save_event_memory(data):
    save_json(EVENT_MEMORY_FILE, data)


def load_cache():
    return load_json(CACHE_FILE, {})


def save_cache(cache):
    save_json(CACHE_FILE, cache)


def get_cached_report(cache_key: str):
    return load_cache().get(cache_key)


def put_cached_report(cache_key: str, report_obj, meta):
    cache = load_cache()
    cache[cache_key] = {
        "report_ru": report_obj["ru"],
        "report_zh": report_obj["zh"],
        "meta": meta,
    }
    save_cache(cache)
