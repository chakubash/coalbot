import os
import time
import inspect
from datetime import datetime, timedelta

from config import BEIJING_TZ, DATA_DIR
from storage import (
    load_state,
    save_state,
    get_cached_report,
    put_cached_report,
    ensure_dirs,
    save_jsonl,
)
from sources import collect_all_candidates
from pipeline.normalize import normalize_and_fetch_details
from pipeline.headline_gatekeeper import filter_raw_candidates
from pipeline.dedup import dedupe_articles
from pipeline.reports import build_bilingual_summary_for_range


def bj_now():
    return datetime.now(BEIJING_TZ)


def slot_times_for_today():
    now = bj_now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "12": day0.replace(hour=12, minute=0, second=0, microsecond=0),
        "20": day0.replace(hour=20, minute=0, second=0, microsecond=0),
    }


def get_current_slot_to_send(now_bj: datetime):
    slots = slot_times_for_today()
    state = load_state()

    if slots["12"] <= now_bj < slots["20"]:
        marker = f'{now_bj.strftime("%Y-%m-%d")}_12'
        if state.get("last_sent_marker_12") != marker:
            return "12"

    if now_bj >= slots["20"]:
        marker = f'{now_bj.strftime("%Y-%m-%d")}_20'
        if state.get("last_sent_marker_20") != marker:
            return "20"

    return None



MANUAL_CACHE_TTL_MINUTES = 45
MANUAL_LOCK_PATH = os.path.join(DATA_DIR, "_manual_summary.lock")
MANUAL_LOCK_STALE_SECONDS = 30 * 60


def _parse_bj_dt(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S").replace(tzinfo=BEIJING_TZ)
    except Exception:
        return None


def _get_recent_manual_summary(max_age_minutes=MANUAL_CACHE_TTL_MINUTES, verbose=False):
    state = load_state()
    result = state.get("last_manual_shared_result")
    generated_at = _parse_bj_dt(state.get("last_manual_shared_generated_at"))
    if not result or not generated_at:
        if verbose:
            print("MANUAL_SHARED_CACHE miss")
        return None

    age_sec = (bj_now() - generated_at).total_seconds()
    if 0 <= age_sec <= max_age_minutes * 60:
        if verbose:
            print(f"В течение последних 45 минут уже была создана актуальная сводка. Отправлена последняя готовая версия без повторной генерации. age_sec={round(age_sec, 1)}")
        return result

    if verbose:
        print(f"MANUAL_SHARED_CACHE expired age_sec={round(age_sec, 1)}")
    return None


def _set_recent_manual_summary(result):
    state = load_state()
    ts = bj_now().strftime("%Y-%m-%d %H:%M:%S")
    state["last_manual_shared_result"] = result
    state["last_manual_shared_generated_at"] = ts
    save_state(state)
    print(f"MANUAL_SHARED_CACHE saved ts={ts}")


def _acquire_manual_lock():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(MANUAL_LOCK_PATH):
            age = time.time() - os.path.getmtime(MANUAL_LOCK_PATH)
            if age > MANUAL_LOCK_STALE_SECONDS:
                try:
                    os.remove(MANUAL_LOCK_PATH)
                    print("MANUAL_LOCK removed stale lock")
                except Exception:
                    pass

        fd = os.open(MANUAL_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"pid={os.getpid()} ts={time.time()}")
        print("MANUAL_LOCK acquired")
        return True
    except FileExistsError:
        print("MANUAL_LOCK busy")
        return False


def _release_manual_lock():
    try:
        if os.path.exists(MANUAL_LOCK_PATH):
            os.remove(MANUAL_LOCK_PATH)
            print("MANUAL_LOCK released")
    except Exception:
        pass


def _wait_for_recent_manual_summary(wait_seconds=300, poll_seconds=2):
    print(f"MANUAL_WAIT start wait_seconds={wait_seconds} poll_seconds={poll_seconds}")
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        cached = _get_recent_manual_summary(verbose=True)
        if cached:
            print("MANUAL_WAIT got shared result")
            return cached
        time.sleep(poll_seconds)
    print("MANUAL_WAIT timeout")
    return None

def get_recent_manual_summary():
    return _get_recent_manual_summary(verbose=False)


def get_manual_window():
    now = bj_now()
    slots = slot_times_for_today()

    today_12 = slots["12"]
    today_20 = slots["20"]
    prev_20 = today_20 - timedelta(days=1)

    if now < today_20:
        return {"kind": "manual_live", "start": prev_20, "end": now}
    return {"kind": "manual_live", "start": today_20, "end": now}


def manual_cache_key(window):
    rounded_end = window["end"].replace(second=0, microsecond=0)
    return f'{window["kind"]}_{window["start"].strftime("%Y%m%d_%H%M")}_{rounded_end.strftime("%Y%m%d_%H%M")}'


def get_last_scheduled_report(slot_name: str):
    state = load_state()
    return state.get(f"last_report_{slot_name}")


def mark_slot_sent(slot_name: str):
    state = load_state()
    if slot_name == "12":
        state["last_sent_marker_12"] = f'{bj_now().strftime("%Y-%m-%d")}_12'
    elif slot_name == "20":
        state["last_sent_marker_20"] = f'{bj_now().strftime("%Y-%m-%d")}_20'
    save_state(state)


def _extract_previous_summary_ru():
    state = load_state()
    for key in ("last_summary_ru", "last_manual_summary_ru"):
        val = state.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


def _safe_get_cached_report(cache_key):
    try:
        sig = inspect.signature(get_cached_report)
        params = list(sig.parameters.values())
    except Exception:
        params = []

    try:
        if len(params) == 1:
            return get_cached_report(cache_key)

        kwargs = {}
        for name in sig.parameters:
            if name in ("key", "cache_key"):
                kwargs[name] = cache_key

        if kwargs:
            return get_cached_report(**kwargs)

        return get_cached_report(cache_key)
    except TypeError:
        return get_cached_report(cache_key)


def _safe_put_cached_report(cache_key, report, meta):
    try:
        sig = inspect.signature(put_cached_report)
        params = list(sig.parameters.values())
    except Exception:
        params = []

    try:
        if len(params) == 2:
            return put_cached_report(cache_key, report)
        if len(params) == 3:
            return put_cached_report(cache_key, report, meta)

        kwargs = {}
        for name in sig.parameters:
            if name in ("key", "cache_key"):
                kwargs[name] = cache_key
            elif name in ("report", "value", "data", "result"):
                kwargs[name] = report
            elif name == "meta":
                kwargs[name] = meta

        if kwargs:
            return put_cached_report(**kwargs)

        try:
            return put_cached_report(cache_key, report, meta)
        except TypeError:
            return put_cached_report(cache_key, report)

    except TypeError:
        try:
            return put_cached_report(cache_key, report, meta)
        except TypeError:
            return put_cached_report(cache_key, report)


def _call_build_summary(*, articles, start_dt, end_dt, run_dir, kind=None):
    sig = inspect.signature(build_bilingual_summary_for_range)

    candidate_kwargs = {
        "articles": articles,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "run_dir": run_dir,
        "kind": kind,
        "previous_summary_ru": _extract_previous_summary_ru(),
    }

    kwargs = {}
    for name in sig.parameters:
        if name in candidate_kwargs:
            kwargs[name] = candidate_kwargs[name]

    return build_bilingual_summary_for_range(**kwargs)


def collect_all_sources_for_range(start_dt, end_dt):
    ensure_dirs()
    run_dir = os.path.join(DATA_DIR, bj_now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)

    raw_candidates = collect_all_candidates()
    print("DEBUG_RAW:", len(raw_candidates))
    save_jsonl(os.path.join(run_dir, "raw_candidates.jsonl"), raw_candidates)

    gated_candidates = filter_raw_candidates(raw_candidates)
    save_jsonl(os.path.join(run_dir, "gated_candidates.jsonl"), gated_candidates)

    normalized, skipped = normalize_and_fetch_details(gated_candidates, start_dt, end_dt)
    save_jsonl(os.path.join(run_dir, "normalized_articles.jsonl"), normalized)
    save_jsonl(os.path.join(run_dir, "skipped_articles.jsonl"), skipped)

    deduped = dedupe_articles(normalized)
    save_jsonl(os.path.join(run_dir, "deduped_articles.jsonl"), deduped)

    return deduped, run_dir


def build_manual_summary():
    shared = _get_recent_manual_summary(verbose=True)
    if shared:
        return shared

    if not _acquire_manual_lock():
        shared = _wait_for_recent_manual_summary(wait_seconds=300, poll_seconds=2)
        if shared:
            return shared
        raise RuntimeError("Manual summary is already being generated.")

    try:
        shared = _get_recent_manual_summary(verbose=True)
        if shared:
            return shared

        window = get_manual_window()
        cache_key = manual_cache_key(window)

        cached = _safe_get_cached_report(cache_key)
        if cached:
            print(f"MANUAL_LOCAL_CACHE hit key={cache_key}")
            _set_recent_manual_summary(cached)
            return cached
        print(f"MANUAL_LOCAL_CACHE miss key={cache_key}")

        print("MANUAL_BUILD start collect_all_sources_for_range")
        articles, run_dir = collect_all_sources_for_range(window["start"], window["end"])
        print(f"MANUAL_BUILD collected articles={len(articles)} run_dir={run_dir}")
        print("MANUAL_BUILD start summary generation")
        result = _call_build_summary(
            articles=articles,
            start_dt=window["start"],
            end_dt=window["end"],
            run_dir=run_dir,
            kind=window["kind"],
        )

        meta = {
            "kind": window["kind"],
            "start": window["start"].strftime("%Y-%m-%d %H:%M:%S"),
            "end": window["end"].strftime("%Y-%m-%d %H:%M:%S"),
            "run_dir": run_dir,
            "generated_at": bj_now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _safe_put_cached_report(cache_key, result, meta)

        state = load_state()
        if isinstance(result, dict):
            if "ru" in result:
                state["last_manual_summary_ru"] = result["ru"]
                state["last_summary_ru"] = result["ru"]
            if "zh" in result:
                state["last_manual_summary_zh"] = result["zh"]
                state["last_summary_zh"] = result["zh"]
        save_state(state)

        print("MANUAL_BUILD summary generation done")
        _set_recent_manual_summary(result)
        return result
    finally:
        _release_manual_lock()


def run_slot(slot_name: str):
    slots = slot_times_for_today()
    slot_dt = slots[slot_name]

    if slot_name == "12":
        start_dt = slots["20"] - timedelta(days=1)
    elif slot_name == "20":
        start_dt = slots["20"] - timedelta(days=1)
    else:
        start_dt = slots["12"]

    articles, run_dir = collect_all_sources_for_range(start_dt, slot_dt)
    result = _call_build_summary(
        articles=articles,
        start_dt=start_dt,
        end_dt=slot_dt,
        run_dir=run_dir,
        kind=slot_name,
    )

    state = load_state()
    state[f"last_report_{slot_name}"] = result

    if isinstance(result, dict):
        if "ru" in result:
            state["last_summary_ru"] = result["ru"]
        if "zh" in result:
            state["last_summary_zh"] = result["zh"]
    save_state(state)

    return result
