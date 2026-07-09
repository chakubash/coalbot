from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

REPORT_BEIJING_TZ = ZoneInfo("Asia/Shanghai") if ZoneInfo else timezone(timedelta(hours=8))


def _to_report_dt(value):
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        try:
            dt = datetime.fromisoformat(text)
        except Exception:
            dt = None
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M",
                "%Y-%m-%d",
                "%Y/%m/%d",
            ):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except Exception:
                    pass
            if dt is None:
                return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=REPORT_BEIJING_TZ)
    return dt.astimezone(REPORT_BEIJING_TZ)

import json
import os
import hashlib
import re
from pathlib import Path
from difflib import SequenceMatcher
from openai import OpenAI

from config import OPENAI_API_KEY, DATA_DIR
from fx import format_price_with_usd
from prompts import build_report_prompt
from storage import save_jsonl
from pipeline.facts import analyze_article, extract_json_from_text
from pipeline.scoring import score_event
from pipeline.safety_terms import is_china_safety_event_text
from sources.client_news import collect_client_news, append_client_news_sections

client = OpenAI(api_key=OPENAI_API_KEY)
REPORT_BUILDER_DAILY_SOURCE_LLM = "REPORT_BUILDER=daily_source_llm"

RU_WEEKDAYS = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}

RU_MONTHS_GEN = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

ZH_WEEKDAYS = {
    0: "星期一",
    1: "星期二",
    2: "星期三",
    3: "星期四",
    4: "星期五",
    5: "星期六",
    6: "星期日",
}

def _format_ru_report_date(dt):
    return f"{RU_WEEKDAYS[dt.weekday()]}, {dt.day} {RU_MONTHS_GEN[dt.month]} {dt.year} года."

def _format_zh_report_date(dt):
    return f"{dt.year}年{dt.month}月{dt.day}日，{ZH_WEEKDAYS[dt.weekday()]}。"

def _sanitize_report_text(text: str) -> str:
    """Remove ugly paywall/open-fragment disclaimers from final reports."""
    if not text:
        return text

    import re

    # Удаляем технические оправдания про неполный доступ/открытую часть.
    patterns = [
        r'Конкретные значения в открытой части не раскрыты[,\.]?\s*',
        r'Конкретные значения в доступной части не раскрыты[,\.]?\s*',
        r'Конкретные значения в открытом фрагменте не раскрыты[,\.]?\s*',
        r'Конкретные значения в доступном фрагменте не раскрыты[,\.]?\s*',
        r'Конкретные уровни в открытой части не приведены[,\.]?\s*',
        r'Конкретные уровни в доступной части не приведены[,\.]?\s*',
        r'Конкретные уровни в открытом фрагменте не приведены[,\.]?\s*',
        r'Конкретные уровни в доступном фрагменте не приведены[,\.]?\s*',
        r'В открытой части (?:статьи|материала|публикации)?\s*не (?:раскрыты|приведены|указаны)[^\.]*\.\s*',
        r'В доступной части (?:статьи|материала|публикации)?\s*не (?:раскрыты|приведены|указаны)[^\.]*\.\s*',
        r'В открытом фрагменте (?:статьи|материала|публикации)?\s*не (?:раскрыты|приведены|указаны)[^\.]*\.\s*',
        r'В доступном фрагменте (?:статьи|материала|публикации)?\s*не (?:раскрыты|приведены|указаны)[^\.]*\.\s*',
        r'Полный текст недоступен[,\.]?\s*',
        r'Нет открытых данных[,\.]?\s*',
        r'Без раскрытия абсолютных значений[,\.]?\s*',
        r'Без раскрытия новых уровней[,\.]?\s*',
        r'без раскрытия абсолютных значений[,\.]?\s*',
        r'без раскрытия новых уровней[,\.]?\s*',
    ]

    for pat in patterns:
        text = re.sub(pat, '', text, flags=re.I)

    # Китайская версия: аналогичные технические фразы.
    zh_patterns = [
        r'公开部分未披露具体数值[，。]?',
        r'公开内容未披露具体数值[，。]?',
        r'可见部分未披露具体数值[，。]?',
        r'可见内容未披露具体数值[，。]?',
        r'未披露具体价格水平[，。]?',
        r'未给出具体数值[，。]?',
        r'由于完整文本不可见[，。]?',
    ]

    for pat in zh_patterns:
        text = re.sub(pat, '', text, flags=re.I)

    text = text.replace(" ,", ",")
    text = text.replace(" .", ".")
    text = text.replace("，。", "。")
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


CACHE_PATH = Path(DATA_DIR) / "article_analysis_cache.json"


def _load_cache():
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_cache(cache: dict):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _cache_key(article: dict) -> str:
    raw = "|".join([
        str(article.get("source", "") or ""),
        str(article.get("url", "") or ""),
        str(article.get("title", "") or ""),
        str(article.get("published_at", "") or ""),
    ])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _title_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _quick_bucket(article: dict) -> str:
    title = str(article.get("title", "") or "").lower()
    content = str(article.get("content", "") or "").lower()
    text = f"{title} {content}"

    if "indonesia" in text and ("export" in text or "shipment" in text):
        return "import_export"
    if "mongolia" in text or "mongolian" in text:
        return "coking"
    if "coking coal" in text or "焦煤" in text or "炼焦煤" in text:
        return "coking"
    if "coke" in text or "焦炭" in text:
        return "coke"
    if "thermal coal" in text or "动力煤" in text:
        return "thermal"
    if "port" in text or "rail" in text or "logistics" in text or "港口" in text or "铁路" in text:
        return "logistics"
    if "policy" in text or "permit" in text or "批准" in text or "政策" in text:
        return "policy"
    if "price" in text or "index" in text or "价格" in text or "指数" in text:
        return "price"
    return "general"


def _quick_score(article: dict) -> int:
    source = str(article.get("source", "") or "")
    title = str(article.get("title", "") or "").lower()
    content = str(article.get("content", "") or "").lower()
    text = f"{title} {content}"

    score = 0

    if source == "sxcoal":
        score += 20
    elif source == "mysteel_fast":
        score += 16
    elif source.startswith("mysteel"):
        score += 12
    elif source == "cls":
        score += 8

    if any(x in text for x in ["export", "import", "shipment", "kpler", "出口", "进口", "发运"]):
        score += 20
    if any(x in text for x in ["price", "index", "yuan", "cny", "价格", "指数", "元/吨"]):
        score += 18
    if any(x in text for x in ["port", "rail", "stock", "inventory", "港口", "库存", "铁路"]):
        score += 12
    if any(x in text for x in ["policy", "permit", "批准", "政策"]):
        score += 10
    if is_china_safety_event_text(text):
        score += 1000
    if any(x in text for x in ["weekly:", "review:", "daily track", "market in figures"]):
        score -= 8
    if any(x in text for x in ["cci chinese", "daily index"]):
        score -= 12

    if any(ch.isdigit() for ch in text):
        score += 8

    return score


def _prefilter_articles_for_llm(articles: list) -> list:
    def _txt(art):
        return f"{art.get('title','')} {art.get('content','')} {art.get('source','')} {art.get('url','')}".lower()

    china_terms = (
        "china", "chinese", "中国", "进口", "到港", "港口", "电厂", "钢厂",
        "tangshan", "唐山", "shanxi", "山西", "shaanxi", "陕西", "ordos", "鄂尔多斯",
        "yulin", "榆林", "qinhuangdao", "秦皇岛", "caofeidian", "曹妃甸",
        "huanghua", "黄骅", "ganqimaodu", "甘其毛都", "ceke", "策克",
        "cfr china", "south china", "north china"
    )

    bad_global = (
        "coal india", "brisbane", "canada", "u.s.", "usa", "united states",
        "magadan", "магадан", "europe requested", "europe", "вьетнам", "vietnam"
    )

    accident_noise = (
        "magadan", "магадан", "collapse", "fatal", "killed", "обруш", "погиб"
    )

    filtered = []
    for art in articles:
        txt = _txt(art)
        has_china = any(t.lower() in txt for t in china_terms)
        is_china_safety = is_china_safety_event_text(txt)

        if is_china_safety:
            filtered.append(art)
            continue

        # Hard remove obvious foreign accident noise.
        if any(t.lower() in txt for t in accident_noise) and not has_china:
            continue

        # Remove weak global stories unless they mention China/import-to-China.
        if any(t.lower() in txt for t in bad_global) and not has_china:
            continue

        filtered.append(art)

    articles = filtered

    forced_prefilter = [art for art in articles if is_china_safety_event_text(_txt(art))]

    ranked = []
    for art in articles:
        ranked.append((art, _quick_bucket(art), _quick_score(art)))

    bucket_limits = {
        "thermal": 4,
        "coking": 5,
        "coke": 2,
        "import_export": 4,
        "logistics": 2,
        "policy": 2,
        "price": 3,
        "general": 2,
    }

    selected = []
    seen_urls = set()

    for bucket in bucket_limits:
        bucket_rows = [x for x in ranked if x[1] == bucket]
        bucket_rows.sort(key=lambda x: x[2], reverse=True)
        for art, _, _score in bucket_rows[:bucket_limits[bucket]]:
            url = str(art.get("url", "") or "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            selected.append(art)

    if len(selected) < 12:
        ranked.sort(key=lambda x: x[2], reverse=True)
        for art, _, _score in ranked:
            url = str(art.get("url", "") or "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            selected.append(art)
            if len(selected) >= 16:
                break

    if forced_prefilter:
        forced_urls = {str(art.get("url", "") or "") for art in forced_prefilter}
        selected = forced_prefilter + [art for art in selected if str(art.get("url", "") or "") not in forced_urls]

    return selected[:16]


def _guess_theme_bucket(row: dict) -> str:
    a = row["analysis"]
    art = row["article"]
    title = str(art.get("title", "") or "").lower()
    event_type = str(a.get("event_type", "") or "")
    segment = str(a.get("segment", "") or "")
    region = str(a.get("region", "") or "")

    if "indonesia" in title and ("export" in title or "shipment" in title):
        return "indonesia_export"
    if "mongolian" in title or "mongolia" in title:
        return "mongolia_coking"
    if "kuzbass" in title or "кузбасс" in title:
        return "russia_supply"
    if "vietnam" in title:
        return "vietnam_supply"
    if event_type in ("price", "price_update") and segment == "coking_coal":
        return f"coking_price_{region or 'general'}"
    if event_type in ("price", "price_update") and segment == "thermal_coal":
        return f"thermal_price_{region or 'general'}"
    if event_type in ("export", "import"):
        return f"{event_type}_{segment}_{region or 'general'}"
    return f"{event_type}_{segment}_{region or 'general'}"


def _merge_similar_rows(rows: list) -> list:
    groups = []

    for row in rows:
        art = row["article"]
        title = str(art.get("title", "") or "")
        bucket = _guess_theme_bucket(row)
        url = str(art.get("url", "") or "")

        matched = None
        for g in groups:
            if bucket != g["bucket"]:
                continue
            sim = _title_sim(title, g["lead"]["article"].get("title", ""))
            if sim >= 0.72:
                matched = g
                break

        if matched is None:
            groups.append({
                "bucket": bucket,
                "lead": row,
                "rows": [row],
                "urls": [url] if url else [],
            })
        else:
            matched["rows"].append(row)
            if url and url not in matched["urls"]:
                matched["urls"].append(url)
            if row.get("score", 0) > matched["lead"].get("score", 0):
                matched["lead"] = row

    merged = []
    for g in groups:
        lead = g["lead"]
        lead = {
            "article": dict(lead["article"]),
            "analysis": dict(lead["analysis"]),
            "score": lead["score"],
            "all_urls": g["urls"],
            "merged_count": len(g["rows"]),
        }
        merged.append(lead)

    merged.sort(key=lambda x: x.get("score", 0), reverse=True)
    return merged


def _dedupe_top_rows(rows: list) -> list:
    rows = _merge_similar_rows(rows)

    kept = []
    seen_theme = {}
    region_limits = {}
    spot_deal_kept = 0

    for row in rows:
        art = row["article"]
        a = row["analysis"]

        title = str(art.get("title", "") or "").lower()
        region = str(a.get("region", "") or "general")
        theme = _guess_theme_bucket(row)

        if "ett sells" in title or "er sells" in title or "auction" in title:
            theme = "spot_deal"

        if theme == "spot_deal":
            if spot_deal_kept >= 1:
                continue
            spot_deal_kept += 1

        if seen_theme.get(theme):
            continue

        if region_limits.get(region, 0) >= 3:
            continue

        seen_theme[theme] = True
        region_limits[region] = region_limits.get(region, 0) + 1
        kept.append(row)

    return kept


def _fallback_top_from_analyzed(analyzed: list, limit: int = 5) -> list:
    """Use strongest analyzed rows if strict China/top gates produced an empty selection."""
    usable = []
    for row in analyzed or []:
        a = row.get("analysis", {}) or {}
        if not a.get("relevant_to_coal", True):
            continue
        if row.get("score", 0) <= 0 and int(a.get("importance_score", 0) or 0) <= 0:
            continue
        usable.append(row)

    if not usable:
        usable = list(analyzed or [])

    usable.sort(
        key=lambda row: (
            int(row.get("score", 0) or 0),
            int((row.get("analysis", {}) or {}).get("importance_score", 0) or 0),
        ),
        reverse=True,
    )
    return usable[:limit]



def _parse_report_dt(value):
    return _to_report_dt(value)

def _source_label(source):
    s = str(source or "").strip().lower()
    if not s:
        return ""
    if "mysteel" in s or "我的钢铁" in s:
        return "Mysteel"
    if "sxcoal" in s or "sx coal" in s:
        return "SXCoal"
    if s == "cls" or "cls" in s or "财联社" in s:
        return "CLS"
    return ""

def _fresh_source_rows(analyzed: list, start_dt, end_dt, limit_per_source: int = 4) -> dict:
    start_dt_cmp = _to_report_dt(start_dt)
    end_dt_cmp = _to_report_dt(end_dt)
    groups = {"Mysteel": [], "SXCoal": [], "CLS": []}
    seen = set()
    sorted_rows = sorted(analyzed or [], key=lambda r: int(r.get("score", 0) or 0), reverse=True)

    for row in sorted_rows:
        art = row.get("article", {}) or {}
        a = row.get("analysis", {}) or {}
        label = _source_label(art.get("source", ""))
        if not label:
            continue
        if not a.get("relevant_to_coal", True):
            continue
        if a.get("repeat_without_new_detail", False) and not is_china_safety_event_text(" ".join([str(art.get("title", "")), str(art.get("content", ""))])):
            continue

        published_at = _parse_report_dt(art.get("published_at", ""))
        if published_at and start_dt_cmp and end_dt_cmp and not (start_dt_cmp <= published_at <= end_dt_cmp):
            continue

        title = str(art.get("title", "") or a.get("headline_fact", "") or "").strip()
        url = str(art.get("url", "") or "").strip()
        key = (label, url or title)
        if not title or key in seen:
            continue
        seen.add(key)
        groups[label].append(row)
        if len(groups[label]) >= limit_per_source:
            continue

    return {k: v[:limit_per_source] for k, v in groups.items() if v}


def _short_ru_item(row: dict) -> str:
    art = row.get("article", {}) or {}
    a = row.get("analysis", {}) or {}
    title = str(a.get("headline_fact") or art.get("title") or "").strip()
    what = str(a.get("what_happened") or "").strip()
    if what and what != title and len(what) <= 180:
        summary = f"{title}. {what}"
    else:
        summary = title
    return summary[:260].rstrip()


def _short_zh_item(row: dict) -> str:
    art = row.get("article", {}) or {}
    a = row.get("analysis", {}) or {}
    title = str(art.get("title") or a.get("headline_fact") or "").strip()
    what = str(a.get("what_happened") or "").strip()
    if what and what != title and len(what) <= 120:
        return f"{title}。{what}"[:220].rstrip()
    return title[:180].rstrip()


def _build_day_picture_ru(source_groups: dict, start_str: str, end_str: str) -> str:
    total = sum(len(v) for v in source_groups.values())
    if not total:
        return "За период свежих полезных сообщений из основных источников не найдено. Рынок выглядит спокойным, новых сигналов по ценам, поставкам или безопасности мало."

    all_text = " ".join(_short_ru_item(r).lower() for rows in source_groups.values() for r in rows)
    parts = [f"За период {start_str}–{end_str} в основных источниках появились новые рыночные сообщения."]
    if any(x in all_text for x in ["事故", "遇难", "авар", "погиб", "安全", "停产整顿"]):
        parts.append("Главный риск — промышленная безопасность: такие новости важны для оценки возможных остановок шахт и реакции надзора.")
    if any(x in all_text for x in ["价格", "цена", "涨", "跌", "指数"]):
        parts.append("По ценам сигнал смешанный: отдельные сообщения показывают локальные движения, но без единой сильной тенденции.")
    if any(x in all_text for x in ["进口", "港口", "库存", "到港", "import", "port"]):
        parts.append("Логистика, импорт и портовые запасы остаются важными ориентирами для закупок и переговоров.")
    if len(parts) == 1:
        parts.append("Общий тон рынка нейтральный: есть рабочие обновления, но без резкого разворота картины дня.")
    return "\n\n".join(parts[:4])


def _build_day_picture_zh(source_groups: dict, start_str: str, end_str: str) -> str:
    total = sum(len(v) for v in source_groups.values())
    if not total:
        return "本期主要来源未发现新的有效消息。市场整体较平稳，价格、供应和安全方面的新信号较少。"
    return f"{start_str}–{end_str}期间，主要来源出现了新的市场消息。整体来看，市场以价格、供应和安全信息为主，需要继续关注矿山安全、港口库存和采购节奏。"


def _log_report_builder_marker(marker: str):
    try:
        with open("bot.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} REPORT_BUILDER={marker}\n")
    except Exception:
        pass


def _is_valid_report_url(url: str) -> bool:
    low = str(url or "").strip().lower()
    return low.startswith("http://") or low.startswith("https://")


def _source_row_payload(row: dict) -> dict:
    art = row.get("article", {}) or {}
    a = row.get("analysis", {}) or {}
    url = art.get("url", "")
    return {
        "source": _source_label(art.get("source", "")),
        "published_at": art.get("published_at", ""),
        "title": art.get("title", ""),
        "headline_fact": a.get("headline_fact", ""),
        "what_happened": a.get("what_happened", ""),
        "event_type": a.get("event_type", ""),
        "segment": a.get("segment", ""),
        "url": url if _is_valid_report_url(url) else "",
        "score": row.get("score", 0),
    }


def _daily_title_hint(kind, end_dt) -> str:
    k = str(kind or "").lower()
    date_ru = f"{end_dt.day} {RU_MONTHS_GEN[end_dt.month]} {end_dt.year} года"
    if k in ("12", "morning") or "morning" in k or "утр" in k:
        return f"⬛ Утренняя сводка по рынку угля КНР за {date_ru}"
    if k in ("20", "evening") or "evening" in k or "вечер" in k:
        return f"⬛ Вечерняя сводка по рынку угля КНР за {date_ru}"
    return f"⬛ Оперативная сводка по рынку угля КНР за {date_ru}"


def _period_hint_ru(start_dt, end_dt) -> str:
    return (
        f"Период: с {start_dt.strftime('%H:%M')} "
        f"{start_dt.day} {RU_MONTHS_GEN[start_dt.month]} "
        f"до {end_dt.strftime('%H:%M')} {end_dt.day} {RU_MONTHS_GEN[end_dt.month]} по Пекину"
    )


def _build_daily_source_prompt(start_dt, end_dt, source_groups: dict, client_items: list, kind=None) -> str:
    payload = {
        "report_date": end_dt.strftime("%Y-%m-%d"),
        "title_hint_ru": _daily_title_hint(kind, end_dt),
        "period_hint_ru": _period_hint_ru(start_dt, end_dt),
        "source_groups": {
            label: [_source_row_payload(row) for row in rows]
            for label, rows in source_groups.items()
        },
        "client_news": client_items or [],
    }
    return (
        "Ты редактор ежедневной сводки для российского участника торговли углем с Китаем. "
        "Напиши качественный финальный отчет на русском и китайском по структурированным данным.\n\n"
        "Верни строго JSON: {\"ru\": \"...\", \"zh\": \"...\"}.\n\n"
        "ОБЯЗАТЕЛЬНАЯ структура русской версии:\n"
        f"{payload['title_hint_ru']}\n"
        f"{payload['period_hint_ru']}\n\n"
        "⬛ Картина дня\n"
        "2–4 коротких абзаца живым деловым русским языком: что произошло, тон рынка, почему это важно для продаж/закупок угля, логистики и переговоров.\n\n"
        "⬛ Новости из источников\n"
        "Группируй только имеющиеся источники: ▪️ Mysteel, ▪️ SXCoal, ▪️ CLS. В каждом пункте русский переведенный заголовок/краткий факт, 1–2 предложения максимум и строка Ссылка: ... только для валидного http/https URL. "
        "Если материал слабый, но релевантный, пиши живо и конкретно: «Тема ... остаётся в фокусе рынка» или «Материал важен как подтверждение продолжающегося внимания к ...».\n\n"
        "⬛ Иные новости\n"
        "Если client_news пустой, напиши ровно: Свежих релевантных новостей по отслеживаемым компаниям за период не найдено.\n\n"
        "Запреты для русской версии: не вставляй китайские иероглифы; не вставляй javascript:void(0); не используй старые заголовки Картина утра, Что изменилось с прошлого дня, Ключевые события утра, Карта рынка, Что отслеживать, Что важно завтра; не пиши шаблонную счетную фразу о количестве свежих полезных сообщений; не используй ISO-формат в строке периода; не пиши канцелярит вроде «перспектива простоев», «новых раскрытых деталей нет», «материал не раскрывает», «в доступной части».\n"
        "Китайская версия должна быть естественной китайской версией того же отчета и идти отдельно в поле zh.\n\n"
        "СТРУКТУРИРОВАННЫЕ ДАННЫЕ:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _daily_report_validation_errors(ru: str) -> list[str]:
    text = ru or ""
    errors = []
    for item in [
        "Картина утра",
        "Что изменилось с прошлого дня",
        "Ключевые события утра",
        "Карта рынка",
        "Что отслеживать",
        "Что важно завтра",
        "importance",
        "debug",
        "status",
        "перспектива простоев",
        "новых раскрытых деталей",
        "новых деталей не раскры",
        "материал не раскрывает",
        "в доступной части",
        "в открытой части",
    ]:
        if item.lower() in text.lower():
            errors.append(f"banned:{item}")
    if re.search(r"найдено\s+\d+\s+свежих\s+полезных\s+сообщ", text, flags=re.I):
        errors.append("generic_count_phrase")
    if re.search(r"[\u4e00-\u9fff]", text):
        errors.append("raw_chinese_in_ru")
    if "javascript:void(0)" in text.lower():
        errors.append("invalid_javascript_url")
    first_line = text.strip().splitlines()[0] if text.strip().splitlines() else ""
    if "сводка по рынку угля кнр" in first_line.lower() and " за " not in first_line.lower():
        errors.append("title_without_date")
    for line in text.splitlines():
        if line.strip().lower().startswith("период:") and re.search(r"\d{4}-\d{2}-\d{2}", line):
            errors.append("iso_period")
            break
    for section in ("Картина дня", "Новости из источников", "Иные новости"):
        if section not in text:
            errors.append(f"missing:{section}")
    return errors


def _call_daily_source_llm(prompt: str) -> dict:
    response = client.responses.create(model="gpt-5.4", input=prompt)
    parsed = extract_json_from_text(response.output_text.strip())
    if not parsed or not parsed.get("ru") or not parsed.get("zh"):
        raise ValueError("daily_source_llm_invalid_json")
    ru = _sanitize_report_text(str(parsed["ru"]).strip())
    zh = _sanitize_report_text(str(parsed["zh"]).strip())
    errors = _daily_report_validation_errors(ru)
    if errors:
        raise ValueError("daily_source_llm_banned_text:" + ",".join(errors))
    return {"ru": ru, "zh": zh}


def _build_source_news_report_llm(start_dt, end_dt, analyzed: list, client_items: list, kind=None) -> dict:
    source_groups = _fresh_source_rows(analyzed, start_dt, end_dt)
    prompt = _build_daily_source_prompt(start_dt, end_dt, source_groups, client_items, kind=kind)
    try:
        return _call_daily_source_llm(prompt)
    except Exception as first_error:
        corrective_prompt = (
            prompt
            + "\n\nПРЕДЫДУЩИЙ ОТВЕТ НЕ ПРОШЕЛ ВАЛИДАЦИЮ: "
            + str(first_error)
            + "\nПерепиши заново. Русский раздел: без китайских иероглифов, без javascript:void(0), без старых заголовков, без ISO-периода, без счетной шаблонной фразы и без канцелярита про раскрытые детали или доступную часть материала."
        )
        return _call_daily_source_llm(corrective_prompt)


def _build_source_news_report(ru_title: str, zh_title: str, start_dt, end_dt, analyzed: list, client_items: list) -> dict:
    start_str = start_dt.strftime("%Y-%m-%d %H:%M")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M")
    report_date = _format_ru_report_date(end_dt)
    source_groups = _fresh_source_rows(analyzed, start_dt, end_dt)

    ru_parts = [
        "⬛ Оперативная сводка по рынку угля КНР",
        f"Дата: {report_date}",
        f"Период: {start_str}–{end_str}",
        "⬛ Картина дня\n" + _build_day_picture_ru(source_groups, start_str, end_str),
        "⬛ Новости из источников",
    ]

    if source_groups:
        source_lines = []
        for label in ("Mysteel", "SXCoal", "CLS"):
            rows = source_groups.get(label) or []
            if not rows:
                continue
            block = [f"▪️ {label}"]
            for i, row in enumerate(rows, 1):
                art = row.get("article", {}) or {}
                block.append(f"{i}. {_short_ru_item(row)}\nСсылка: {art.get('url', '')}")
            source_lines.append("\n".join(block))
        ru_parts[-1] += "\n" + "\n\n".join(source_lines)
    else:
        ru_parts[-1] += "\nСвежих релевантных новостей из Mysteel / SXCoal / CLS за период не найдено."

    zh_parts = [
        zh_title,
        f"日期：{_format_zh_report_date(end_dt)}",
        f"期间：{start_str}–{end_str}",
        "⬛ 今日概况\n" + _build_day_picture_zh(source_groups, start_str, end_str),
        "⬛ 来源新闻",
    ]
    if source_groups:
        zh_source_lines = []
        for label in ("Mysteel", "SXCoal", "CLS"):
            rows = source_groups.get(label) or []
            if not rows:
                continue
            block = [f"▪️ {label}"]
            for i, row in enumerate(rows, 1):
                art = row.get("article", {}) or {}
                block.append(f"{i}. {_short_zh_item(row)}\n链接：{art.get('url', '')}")
            zh_source_lines.append("\n".join(block))
        zh_parts[-1] += "\n" + "\n\n".join(zh_source_lines)
    else:
        zh_parts[-1] += "\n本期未发现来自 Mysteel / SXCoal / CLS 的有效新消息。"

    ru, zh = "\n\n".join(ru_parts), "\n\n".join(zh_parts)
    ru, zh = append_client_news_sections(ru, zh, client_items)
    return {"ru": _sanitize_report_text(ru), "zh": _sanitize_report_text(zh)}



def _get_title(kind, end_dt):
    months = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля",
        5: "мая", 6: "июня", 7: "июля", 8: "августа",
        9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
    }
    date_ru = f"{end_dt.day} {months[end_dt.month]} {end_dt.year} года"
    if kind == "manual_live":
        return f"⬛ Оперативная сводка за {date_ru}"
    if kind == "12":
        return f"⬛ Утренняя сводка за {date_ru}"
    if kind == "20":
        return f"⬛ Вечерняя сводка за {date_ru}"
    if kind == "weekly":
        return "⬛ Недельная сводка"
    if kind == "monthly":
        return "⬛ Месячная сводка"
    return f"⬛ Сводка за {date_ru}"


def _get_title_zh(kind, end_dt):
    date_zh = f"{end_dt.year}年{end_dt.month}月{end_dt.day}日"
    if kind == "manual_live":
        return f"⬛ 实时煤炭摘要（{date_zh}）"
    if kind == "12":
        return f"⬛ 早间煤炭摘要（{date_zh}）"
    if kind == "20":
        return f"⬛ 晚间煤炭摘要（{date_zh}）"
    if kind == "weekly":
        return "⬛ 周度煤炭摘要"
    if kind == "monthly":
        return "⬛ 月度煤炭摘要"
    return f"⬛ 煤炭摘要（{date_zh}）"


def build_bilingual_summary_for_range(articles, previous_summary_ru, start_dt, end_dt, run_dir, kind=None):
    title_ru = _get_title(kind, end_dt)
    title_zh = _get_title_zh(kind, end_dt)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M")
    today_str = end_dt.strftime("%Y-%m-%d")
    report_date_ru = _format_ru_report_date(end_dt)
    report_date_zh = _format_zh_report_date(end_dt)

    def _should_add_client_news():
        return str(kind or "").lower() not in ("weekly", "monthly")

    def _load_client_news_items():
        if not _should_add_client_news():
            return []
        debug_rows = []
        try:
            items = collect_client_news(start_dt, end_dt, debug_rows=debug_rows, run_dir=str(run_dir))
            save_jsonl(os.path.join(run_dir, "client_news.jsonl"), items)
            save_jsonl(os.path.join(run_dir, "client_news_debug.jsonl"), debug_rows)
            return items
        except Exception:
            save_jsonl(os.path.join(run_dir, "client_news.jsonl"), [])
            save_jsonl(os.path.join(run_dir, "client_news_debug.jsonl"), debug_rows)
            return []

    candidate_articles = _prefilter_articles_for_llm(articles)
    cache = _load_cache()

    analyzed = []
    for article in candidate_articles:
        url = str(article.get("url", "")).lower()
        if "/subject/" in url or "/zt/" in url:
            continue

        key = _cache_key(article)
        cached = cache.get(key)

        try:
            if cached:
                a = cached
            else:
                a = analyze_article(article)
                cache[key] = a

            s = score_event(a, article)
            analyzed.append({
                "article": article,
                "analysis": a,
                "score": s
            })
        except Exception:
            continue

    _save_cache(cache)
    save_jsonl(os.path.join(run_dir, "analyzed_articles.jsonl"), analyzed)

    good = []
    for row in analyzed:
        a = row["analysis"]

        if not a.get("relevant_to_coal", True):
            continue
        if a.get("should_enter_top8") is False:
            continue
        if a.get("repeat_without_new_detail", False):
            continue
        if a.get("importance_score", 0) < 18:
            continue
        if row.get("score", 0) < 18:
            continue

        good.append(row)

    if len(good) < 6:
        relaxed = []
        for row in analyzed:
            a = row["analysis"]
            if not a.get("relevant_to_coal", True):
                continue
            if a.get("repeat_without_new_detail", False):
                continue
            if row.get("score", 0) < 15:
                continue
            relaxed.append(row)
        good = relaxed

    good.sort(key=lambda x: x["score"], reverse=True)
    good = _dedupe_top_rows(good)

    # HARD FINAL GATE:
    # This bot is for a Russian coal exporter/import-chain participant focused on China.
    # It must not turn into a generic global coal digest.
    CHINA_CORE_TERMS = (
        "china", "chinese", "中国", "国内", "华北", "华东", "华南", "沿海",
        "进口煤", "进口焦煤", "进口动力煤", "中国进口", "到港", "港口", "港口库存",
        "电厂", "钢厂", "焦企", "煤矿", "安监", "安全检查",
        "tangshan", "唐山", "shanxi", "山西", "shaanxi", "陕西",
        "ordos", "鄂尔多斯", "yulin", "榆林", "lüliang", "lvliang", "吕梁",
        "qinhuangdao", "秦皇岛", "caofeidian", "曹妃甸", "huanghua", "黄骅",
        "ganqimaodu", "甘其毛都", "ceke", "策克",
        "cfr china", "south china", "north china", "bohai", "环渤海",
        "tangshan price", "port price", "domestic coal price"
    )

    DIRECT_CHINA_IMPORT_TERMS = (
        "cfr china", "delivered to china", "china import", "imports into china",
        "shipments to china", "exports to china", "china-bound",
        "south china port", "north china port",
        "中国进口", "到港", "进口到中国", "运往中国", "发往中国", "华南港口", "北方港口"
    )

    CHINA_SUPPLIER_TERMS = (
        "mongol", "mongolia", "蒙古", "ganqimaodu", "甘其毛都", "ceke", "策克",
        "indonesia", "indonesian", "印尼",
        "russia", "russian", "俄罗斯",
        "australia", "australian", "澳大利亚"
    )

    TRADE_TERMS = (
        "import", "export", "shipment", "shipments", "cargo", "cfr", "fob",
        "port", "rail", "freight", "logistics",
        "进口", "出口", "发运", "到港", "铁路", "港口", "海运费"
    )

    BAD_GLOBAL_TERMS = (
        "coal india", "india", "印度", "brisbane", "canada", "加拿大",
        "u.s.", "usa", "united states", "美国",
        "magadan", "магадан", "colombia", "south africa", "poland",
        "europe requested", "europe", "европа", "vietnam", "вьетнам"
    )

    ACCIDENT_TERMS = (
        "accident", "fatal", "killed", "collapse", "mine collapse",
        "обруш", "погиб", "авар", "взрыв"
    )

    def _row_text(row):
        art = row.get("article", {}) or {}
        a = row.get("analysis", {}) or {}
        return " ".join([
            str(art.get("title", "") or ""),
            str(art.get("content", "") or ""),
            str(art.get("source", "") or ""),
            str(art.get("url", "") or ""),
            str(a.get("headline_fact", "") or ""),
            str(a.get("what_happened", "") or ""),
            str(a.get("exporter_note", "") or ""),
            str(a.get("event_type", "") or ""),
            str(a.get("segment", "") or ""),
            str(a.get("region", "") or ""),
        ]).lower()

    def _has_any(txt, terms):
        return any(t.lower() in txt for t in terms)

    def _is_china_core(row):
        txt = _row_text(row)
        return _has_any(txt, CHINA_CORE_TERMS) or _has_any(txt, DIRECT_CHINA_IMPORT_TERMS)

    def _is_china_supplier_relevant(row):
        txt = _row_text(row)
        return _has_any(txt, CHINA_SUPPLIER_TERMS) and (
            _has_any(txt, DIRECT_CHINA_IMPORT_TERMS)
            or ("china" in txt or "中国" in txt)
            or ("cfr" in txt and ("port" in txt or "港" in txt))
            or ("进口" in txt and ("煤" in txt or "coal" in txt))
        )

    def _is_generic_global(row):
        txt = _row_text(row)
        return _has_any(txt, BAD_GLOBAL_TERMS) and not (_is_china_core(row) or _is_china_supplier_relevant(row))

    def _is_foreign_accident_noise(row):
        txt = _row_text(row)
        return _has_any(txt, ACCIDENT_TERMS) and not (_is_china_core(row) or _is_china_supplier_relevant(row))

    def _priority(row):
        txt = _row_text(row)
        base = int(row.get("score", 0) or 0)

        if _is_foreign_accident_noise(row):
            return -10000

        if _is_china_core(row):
            base += 1000

        if _is_china_supplier_relevant(row):
            base += 500

        # direct China market indicators
        for t in (
            "tangshan", "唐山", "ordos", "鄂尔多斯", "yulin", "榆林", "吕梁",
            "qinhuangdao", "秦皇岛", "caofeidian", "曹妃甸", "huanghua", "黄骅",
            "ganqimaodu", "甘其毛都", "ceke", "策克",
            "cfr china", "进口煤", "进口焦煤", "进口动力煤", "港口库存", "电厂", "钢厂"
        ):
            if t.lower() in txt:
                base += 80

        if _is_generic_global(row):
            base -= 800

        return base

    # 1) remove foreign accident noise completely
    good = [r for r in good if not _is_foreign_accident_noise(r)]

    china_core = [r for r in good if _is_china_core(r)]
    china_supply = [r for r in good if (not _is_china_core(r)) and _is_china_supplier_relevant(r)]
    global_background = [r for r in good if not _is_china_core(r) and not _is_china_supplier_relevant(r) and not _is_generic_global(r)]
    weak_global = [r for r in good if _is_generic_global(r)]

    china_core.sort(key=_priority, reverse=True)
    china_supply.sort(key=_priority, reverse=True)
    global_background.sort(key=_priority, reverse=True)
    weak_global.sort(key=_priority, reverse=True)

    selected = []

    # First fill with China core.
    for r in china_core:
        selected.append(r)
        if len(selected) >= 6:
            break

    # Then China-relevant suppliers.
    if len(selected) < 6:
        for r in china_supply:
            selected.append(r)
            if len(selected) >= 6:
                break

    # Only if still less than 5, add non-bad background.
    if len(selected) < 5:
        for r in global_background:
            selected.append(r)
            if len(selected) >= 5:
                break

    # Weak global news may enter only as the final 6th item, never above.
    if len(selected) < 6 and len(selected) >= 4:
        for r in weak_global:
            selected.append(r)
            break

    def _row_is_low_value_top(row):
        try:
            art = row.get("article", {}) or {}
            a = row.get("analysis", {}) or {}

            title = str(art.get("title", "") or "").lower()
            content = str(art.get("content", "") or "").lower()
            headline = str(a.get("headline_fact", "") or "").lower()
            what = str(a.get("what_happened", "") or "").lower()
            event_type = str(a.get("event_type", "") or "").lower()
            segment = str(a.get("segment", "") or "").lower()
            score = int(a.get("importance_score") or 0)

            text = " ".join([title, content, headline, what])

            low_terms = [
                "招标公告", "招标", "中标",
                "煤炭板块", "涨停", "股票", "stock",
                "水泥", "cement",
                "公司成立", "成立新公司", "注册资本", "business scope",
                "价格稳定", "市场稳定", "持稳", "暂稳",
            ]

            strong_terms = [
                "事故", "矿难", "安全检查", "停产", "限产", "复产",
                "涨超", "跌超", "上调", "下调", "上涨", "下跌",
                "进口", "到港", "甘其毛都", "策克", "蒙古", "蒙煤",
                "库存", "港口", "海运费", "运费", "电厂", "钢厂",
                "cfr", "shipment", "import", "export",
            ]

            has_strong = any(x in text for x in strong_terms)

            # Очень слабое событие не должно попадать в топ.
            if score and score < 35 and not has_strong:
                return True

            # Низкоприоритетные темы можно пропустить, если в них нет сильного рыночного сигнала.
            if any(x in text for x in low_terms) and not has_strong:
                return True

            # Просто стабильная региональная котировка без движения — не топ, если нет другого сигнала.
            if event_type in ("price", "price_update") and "稳定" in text and not has_strong:
                return True

            return False
        except Exception:
            return False

    def _is_china_accident_or_safety(row):
        try:
            art = row.get("article", {}) or {}
            a = row.get("analysis", {}) or {}

            title = str(art.get("title", "") or "")
            content = str(art.get("content", "") or "")
            headline = str(a.get("headline_fact", "") or "")
            what = str(a.get("what_happened", "") or "")
            event_type = str(a.get("event_type", "") or "").lower()

            text = " ".join([title, content, headline, what]).lower()

            accident_terms = [
                "事故", "矿难", "坍塌", "塌方", "冒顶", "透水", "瓦斯", "爆炸",
                "遇难", "死亡", "伤者", "受伤", "被困", "救援",
                "非法煤矿", "非法开采", "非法生产", "无证",
                "安全生产", "安全检查", "安全监管", "督查", "整治",
                "停产整顿", "责令停产", "瞒报", "谎报", "造假",
                "accident", "mine accident", "collapse", "gas explosion",
                "illegal mine", "illegal mining", "fatal", "killed", "dead",
                "safety inspection", "safety crackdown", "production halt"
            ]

            china_terms = [
                "中国", "山西", "云南", "会泽", "临汾", "长治", "吕梁",
                "陕西", "内蒙古", "贵州", "河南", "河北", "山东", "新疆",
                "china", "shanxi", "yunnan", "huize", "linfen", "changzhi"
            ]

            foreign_terms = [
                "india", "indonesia", "australia", "usa", "canada", "south africa",
                "индонез", "индия", "австрал", "сша", "канада", "юар"
            ]

            has_accident = event_type in ("accident", "safety", "shutdown") or any(x in text for x in accident_terms)
            has_china = any(x in text for x in china_terms)
            has_foreign = any(x in text for x in foreign_terms)

            # Для китайских аварий/проверок — всегда top-candidate.
            return is_china_safety_event_text(text) or (has_accident and has_china and not has_foreign)
        except Exception:
            return False

    # Китайские аварии, промбез, проверки и остановки после аварий нельзя терять:
    # они должны идти выше обычных price snippets.
    forced_safety = [r for r in good if _is_china_accident_or_safety(r)]

    # Убираем дубли forced_safety по URL.
    _forced_seen = set()
    _forced_unique = []
    for r in forced_safety:
        art = r.get("article", {}) or {}
        url = str(art.get("url", "") or "").strip()
        if url and url in _forced_seen:
            continue
        if url:
            _forced_seen.add(url)
        _forced_unique.append(r)

    if _forced_unique:
        selected = _forced_unique + [r for r in selected if r not in _forced_unique]

    # If there are fewer than 4 China-related items, do NOT pad with trash to 6.
    selected = [r for r in selected if (_is_china_accident_or_safety(r) or not _row_is_low_value_top(r))]

    # Убираем явные дубли по URL до передачи в LLM.
    _seen_urls = set()
    _dedup_selected = []
    for r in selected:
        art = r.get("article", {}) or {}
        url = str(art.get("url", "") or "").strip()
        if url and url in _seen_urls:
            continue
        if url:
            _seen_urls.add(url)
        _dedup_selected.append(r)
    selected = _dedup_selected

    # Не добираем мусором: лучше 3–4 сильных события, чем 5–6 слабых.
    top = selected[:5]

    if not top and analyzed:
        top = _fallback_top_from_analyzed(analyzed)

    if _should_add_client_news():
        client_items = _load_client_news_items()
        try:
            _log_report_builder_marker("daily_source_llm")
            result = _build_source_news_report_llm(start_dt, end_dt, analyzed, client_items, kind=kind)
        except Exception:
            _log_report_builder_marker("daily_source_fallback")
            result = {
                "ru": "Не удалось подготовить качественную AI-сводку. Попробуйте позже.",
                "zh": "未能生成高质量AI简报，请稍后再试。",
            }
        with open(os.path.join(run_dir, "final_summary_ru.txt"), "w", encoding="utf-8") as f:
            f.write(result["ru"])
        with open(os.path.join(run_dir, "final_summary_zh.txt"), "w", encoding="utf-8") as f:
            f.write(result["zh"])
        return result

    if not top:
        is_weekend = False
        try:
            is_weekend = end_dt.weekday() in (5, 6)  # Saturday / Sunday
        except Exception:
            is_weekend = False

        if is_weekend:
            ru = (
                f"{title_ru}\n\n"
                f"⬛ Картина периода\n"
                f"Сегодня выходной день в Китае, поэтому отраслевых публикаций и рыночных обновлений меньше обычного. "
                f"За выбранный период значимых новостей по угольному рынку КНР не найдено.\n\n"
                f"Если за выходные появится важное событие, оно будет отражено в следующей сводке.\n"
            )

            zh = (
                f"{title_zh}\n\n"
                f"⬛ 本期情况\n"
                f"今天是中国周末休息日，行业发布和市场更新少于工作日。"
                f"本期未发现中国煤炭市场的重要消息。\n\n"
                f"如果周末期间出现重要事件，将在下一期简报中反映。\n"
            )
        else:
            ru = (
                f"{title_ru}\n\n"
                f"⬛ Картина периода\n"
                f"За выбранный период значимых новостей по угольному рынку КНР не найдено.\n\n"
                f"Если важное обновление появится позже, оно будет отражено в следующей сводке.\n"
            )

            zh = (
                f"{title_zh}\n\n"
                f"⬛ 本期情况\n"
                f"本期未发现中国煤炭市场的重要消息。\n\n"
                f"如果后续出现重要更新，将在下一期简报中反映。\n"
            )

        ru = _sanitize_report_text(ru)
        zh = _sanitize_report_text(zh)

        if _should_add_client_news():
            ru, zh = append_client_news_sections(ru, zh, _load_client_news_items())

        with open(os.path.join(run_dir, "final_summary_ru.txt"), "w", encoding="utf-8") as f:
            f.write(ru)
        with open(os.path.join(run_dir, "final_summary_zh.txt"), "w", encoding="utf-8") as f:
            f.write(zh)
        return {"ru": ru, "zh": zh}


    def _is_evening_report():
        """
        Вечерним считаем только явно вечерний слот.
        Нельзя определять вечер по одному end_dt.hour, иначе ручной/полуденный запуск
        может случайно стать вечерней сводкой и получить период 07:00–20:00.
        """
        try:
            k = str(kind or "").lower()

            # Явно утренние/дневные режимы всегда НЕ вечерние.
            morning_markers = [
                "morning", "утр", "12", "1200", "noon",
                "slot_12", "scheduled_12", "manual_morning"
            ]
            if any(x in k for x in morning_markers):
                return False

            # Явно вечерние режимы.
            evening_markers = [
                "evening", "вечер", "20", "2000", "pm",
                "slot_20", "scheduled_20", "manual_evening"
            ]
            if any(x in k for x in evening_markers):
                return True

            # manual_live сам по себе не вечерний. Его тип должен задаваться временем ниже.
            if "manual_live" in k or "manual" in k:
                try:
                    h = int(getattr(end_dt, "hour", 0))
                    return h >= 18
                except Exception:
                    return False

        except Exception:
            pass

        # Для неизвестного kind безопаснее считать отчёт утренним/оперативным,
        # чем ошибочно превращать его в вечерний.
        return False

    def _load_morning_context_ru():
        if not _is_evening_report():
            return ""

        try:
            from pathlib import Path
            base = Path(DATA_DIR)
            day = end_dt.strftime("%Y%m%d")

            candidates = sorted(base.glob(f"{day}_12*/final_summary_ru.txt"), reverse=True)
            for fp in candidates:
                try:
                    txt = fp.read_text(encoding="utf-8").strip()
                    if txt:
                        return txt[:12000]
                except Exception:
                    continue
        except Exception:
            pass

        try:
            if previous_summary_ru:
                return str(previous_summary_ru)[:12000]
        except Exception:
            pass

        return ""

    morning_context_ru = _load_morning_context_ru()

    event_blocks = []
    for i, row in enumerate(top, 1):
        art = row["article"]
        a = row["analysis"]

        formatted_price = ""
        if a.get("has_numeric_price") and a.get("price_value") and a.get("price_currency"):
            try:
                formatted_price = format_price_with_usd(
                    a.get("price_value"),
                    a.get("price_currency"),
                    a.get("price_unit", "")
                )
            except Exception:
                formatted_price = f"{a.get('price_value')} {a.get('price_currency')}"

        all_urls = row.get("all_urls") or [art.get("url")]
        all_urls = [x for x in all_urls if x]
        lead_url = all_urls[0] if all_urls else ""
        extra_urls = all_urls[1:]

        block = (
            f"СОБЫТИЕ {i}\n"
            f"Источник: {art.get('source')}\n"
            f"Время: {art.get('published_at')}\n"
            f"Заголовок: {art.get('title')}\n"
            f"Факт: {a.get('headline_fact','')}\n"
            f"Что произошло: {a.get('what_happened','')}\n"
            f"Цена: {formatted_price}\n"
            f"Тип события: {a.get('event_type','')}\n"
            f"Сегмент: {a.get('segment','')}\n"
            f"Влияние на цену сегодня: {a.get('price_impact_today','')}\n"
            f"Релевантность экспортёру: {a.get('exporter_relevance','')}\n"
            f"Ссылка: {lead_url}"
        )
        if extra_urls:
            block += "\nДоп. ссылки:\n" + "\n".join(f"- {u}" for u in extra_urls)
        event_blocks.append(block)

    response = client.responses.create(
        model="gpt-5.4",
        input=build_report_prompt(
            "\n\n".join(event_blocks),
            today_str,
            start_str,
            end_str,
            morning_context_ru=morning_context_ru
        )
    )

    raw = response.output_text.strip()
    parsed = extract_json_from_text(raw)

    if not parsed or "ru" not in parsed or "zh" not in parsed:
        ru = raw
        zh = "未能自动生成中文版本。"
    else:
        ru = parsed["ru"].strip()
        zh = parsed["zh"].strip()

    import re

    def _default_ru_header():
        return "⬛ Вечерняя сводка по рынку угля КНР" if _is_evening_report() else "⬛ Утренняя сводка по рынку угля КНР"

    def _default_zh_header():
        return "⬛ 中国煤炭市场晚间简报" if _is_evening_report() else "⬛ 中国煤炭市场早间简报"

    def _remove_empty_market_map_bullets(text: str, lang: str) -> str:
        import re

        if not text:
            return text

        if lang == "ru":
            bad_patterns = [
                r'нет\s+новых\s+значимых\s+сигналов',
                r'новых\s+значимых\s+сигналов\s+.*?не\s+было',
                r'значимых\s+обновлений\s+.*?не\s+поступало',
                r'в\s+доступных\s+материалах\s+.*?не\s+было',
                r'в\s+материалах\s+периода\s+.*?не\s+было',
                r'данных\s+.*?не\s+было',
                r'сигналов\s+.*?не\s+было',
                r'не\s+поступало',
            ]
            section_names = r'(?:Карта рынка на утро|Карта рынка к вечеру|Карта рынка на период)'
        else:
            bad_patterns = [
                r'没有新的重要信号',
                r'未出现新的重要信号',
                r'未见新的重要信号',
                r'没有显著更新',
                r'未有显著更新',
                r'暂无重要信息',
                r'没有相关数据',
            ]
            section_names = r'(?:早间市场图景|晚间市场图景|市场图景|市场结构)'

        def clean_section(m):
            header = m.group(1)
            body = m.group(2)
            tail = m.group(3)

            lines = body.splitlines()
            kept = []

            for line in lines:
                stripped = line.strip()
                if stripped.startswith("▪️"):
                    low = stripped.lower()
                    if any(re.search(pat, low, flags=re.I) for pat in bad_patterns):
                        continue
                kept.append(line)

            cleaned_body = "\n".join(kept).strip()

            # Если после удаления в карте рынка не осталось пунктов, убираем весь блок.
            if not any(x.strip().startswith("▪️") for x in cleaned_body.splitlines()):
                return tail.lstrip()

            return header + "\n" + cleaned_body + "\n\n" + tail.lstrip()

        pattern = rf'(⬛ {section_names}\n)(.*?)(\n\n⬛ |\Z)'
        return re.sub(pattern, clean_section, text, flags=re.S)

    def _cleanup_generated_text(text: str, default_header: str, lang: str) -> str:
        text = (text or "").strip()

        # Убираем старые служебные блоки, если модель или старый prompt их вернули.
        if lang == "ru":
            text = re.sub(r'\n*⬛ Период обзора:\n▪️ .*?(?=\n\n⬛ )\n?', '\n\n', text, flags=re.S)
            text = re.sub(r'\n\n⬛ Вывод:\s*$', '', text, flags=re.S).strip()
        else:
            text = re.sub(r'\n*⬛ (?:回顾期间|回顾期|观察期|回顾周期)：\n▪️ .*?(?=\n\n⬛ )\n?', '\n\n', text, flags=re.S)
            text = re.sub(r'\n\n⬛ 结论：\s*$', '', text, flags=re.S).strip()

        text = _remove_empty_market_map_bullets(text, lang)
        text = re.sub(r'\n{3,}', '\n\n', text).strip()

        # Если модель не дала заголовок, добавляем новый дефолтный.
        if text and not text.startswith("⬛ "):
            text = f"{default_header}\n\n{text}"
        elif not text:
            text = default_header

        # Убираем случайное двойное повторение первого заголовка.
        text = re.sub(r'^(⬛ .*?)\n\n\1\n\n', r'\1\n\n', text, count=1, flags=re.S)

        # Схлопываем полное дублирование текста.
        lines = text.strip().splitlines()
        if len(lines) % 2 == 0:
            half = len(lines) // 2
            if lines[:half] == lines[half:]:
                text = "\n".join(lines[:half])

        return re.sub(r'\n{3,}', '\n\n', text).strip()

    ru = _cleanup_generated_text(ru, _default_ru_header(), "ru")
    zh = _cleanup_generated_text(zh, _default_zh_header(), "zh")

    ru = _sanitize_report_text(ru)
    zh = _sanitize_report_text(zh)

    if _should_add_client_news():
        ru, zh = append_client_news_sections(ru, zh, _load_client_news_items())

    with open(os.path.join(run_dir, "final_summary_ru.txt"), "w", encoding="utf-8") as f:
        f.write(ru)
    with open(os.path.join(run_dir, "final_summary_zh.txt"), "w", encoding="utf-8") as f:
        f.write(zh)

    return {"ru": ru, "zh": zh}
