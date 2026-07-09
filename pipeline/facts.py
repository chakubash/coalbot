import json
import re
from openai import OpenAI

from config import OPENAI_API_KEY
from prompts import build_fact_prompt
from pipeline.safety_terms import is_china_safety_event_text
from utils import enforce_segment_consistency, detect_coal_commodity

client = OpenAI(api_key=OPENAI_API_KEY)

BLOCK_IN_FACTS = [
    "petcoke", "petroleum coke", "needle coke", "calcined petcoke",
    "石油焦", "针状焦", "煅烧焦",
    "aluminum", "aluminium", "铝",
    "building materials", "rebar", "建筑钢材", "螺纹钢", "高线", "盘螺",
    "steel project", "项目开工", "项目投产",
    "photovoltaic", "solar", "光伏", "新能源项目", "单体最大光伏项目"
]

LOW_SIGNAL_PATTERNS = [
    "ett sells",
    "er sells",
    "daily track",
    "daily index",
    "market in figures",
    "purchase price",
    "coal daily track",
    "cci chinese",
]

REVIEW_PATTERNS = [
    "weekly:",
    "review:",
    "daily track",
    "market in figures",
    "index (apr",
]

def extract_json_from_text(text: str):
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    raw = text[start:end + 1]
    try:
        return json.loads(raw)
    except Exception:
        return None


def _has_strong_number(text_blob: str) -> bool:
    patterns = [
        r"\b\d+(?:\.\d+)?\s*(%|mt|kt|million|billion|yuan|cny|usd|\$|元|吨)\b",
        r"\b\d+(?:\.\d+)?\s*(year|month|yr|mth)s?\s+low\b",
        r"\blowest\b.*\b(year|month|yr|mth)",
        r"\b\d+(?:\.\d+)?\s*%\s*(yoy|mom|year on year|month on month|from february|from january)\b",
        r"\bthird month\b|\bfourth month\b|\bfifth month\b",
        r"\bexports?\b.*\bfell\b|\bexports?\b.*\brose\b|\bshipments?\b.*\bfell\b|\bshipments?\b.*\brose\b",
    ]
    return any(re.search(p, text_blob, re.I) for p in patterns)


def _is_high_value_flow_story(text_blob: str) -> bool:
    flow_terms = [
        "export", "exports", "shipment", "shipments",
        "import", "imports", "cargo", "cargoes",
        "kpler", "port", "seaborne",
        "indonesia", "australia", "russia", "mongolia", "china shipments"
    ]
    return any(x in text_blob for x in flow_terms)


def _apply_post_rules(article: dict, parsed: dict):
    title = str(article.get("title", "") or "")
    content = str(article.get("content", "") or "")
    text_blob = f"{title}\n{content}".lower()

    if not parsed.get("relevant_to_coal", True):
        return parsed

    has_price = bool(parsed.get("has_numeric_price"))
    has_price_value = parsed.get("price_value") not in (None, "", "null")
    has_strong_number = _has_strong_number(text_blob)
    low_signal = any(x in text_blob for x in LOW_SIGNAL_PATTERNS)
    review_like = any(x in text_blob for x in REVIEW_PATTERNS)
    high_value_flow = _is_high_value_flow_story(text_blob)

    # Единичные spot/deal/daily-index без цены и без сильных цифр — не top event
    if low_signal and not has_price and not has_price_value and not has_strong_number:
        parsed["importance_score"] = min(int(parsed.get("importance_score", 0)), 12)
        parsed["repeat_without_new_detail"] = True
        parsed["should_enter_top8"] = False
        parsed["new_fact_present"] = False

    # Review/weekly режем только если это реально обзор без нового сильного факта
    if review_like and not has_price and not has_strong_number and not high_value_flow and "mongolian" not in text_blob and "mongolia" not in text_blob:
        parsed["importance_score"] = min(int(parsed.get("importance_score", 0)), 16)
        if parsed.get("event_type") in ("other", "", None):
            parsed["repeat_without_new_detail"] = True
            parsed["should_enter_top8"] = False
            parsed["new_fact_present"] = False


    # Монголия + импорт/цены по коксующемуся углю — отдельный важный кейс, даже если формат weekly
    if ("mongolia" in text_blob or "mongolian" in text_blob) and ("import" in text_blob or "coking coal" in text_blob):
        if parsed.get("event_type") in ("price", "price_update", "import", "other"):
            parsed["repeat_without_new_detail"] = False
            parsed["should_enter_top8"] = True
            parsed["new_fact_present"] = True
            parsed["importance_score"] = max(int(parsed.get("importance_score", 0)), 45)
            if parsed.get("event_type") in ("other", "", None):
                parsed["event_type"] = "import"

    # Но если это import/export flow story с цифрами/сильным сдвигом — не убивать
    if high_value_flow and (has_strong_number or "kpler" in text_blob):
        parsed["new_fact_present"] = True
        parsed["repeat_without_new_detail"] = False
        parsed["should_enter_top8"] = True
        parsed["importance_score"] = max(int(parsed.get("importance_score", 0)), 55)
        if parsed.get("event_type") in ("other", "", None):
            if "export" in text_blob or "shipment" in text_blob:
                parsed["event_type"] = "export"
            elif "import" in text_blob:
                parsed["event_type"] = "import"
        if parsed.get("exporter_relevance", "low") == "low":
            parsed["exporter_relevance"] = "medium"


    # Явные ценовые апдейты с числом не должны случайно выпадать из top
    if parsed.get("event_type") in ("price", "price_update"):
        if has_price or has_price_value or has_strong_number:
            if not parsed.get("repeat_without_new_detail", False):
                parsed["should_enter_top8"] = True
                parsed["new_fact_present"] = True
                parsed["importance_score"] = max(int(parsed.get("importance_score", 0)), 58)


    # Mysteel fast price updates по углю — это допустимые оперативные ценовые сигналы
    if article.get("source") == "mysteel_fast":
        if parsed.get("event_type") in ("price", "price_update"):
            if has_price or has_price_value or "价格指数" in text_blob or "价格" in text_blob:
                parsed["repeat_without_new_detail"] = False
                parsed["should_enter_top8"] = True
                parsed["new_fact_present"] = True
                parsed["importance_score"] = max(int(parsed.get("importance_score", 0)), 58)

    # Export/import flow stories с новыми цифрами тоже не должны выпадать
    if parsed.get("event_type") in ("export", "import"):
        if has_strong_number or high_value_flow:
            if not parsed.get("repeat_without_new_detail", False):
                parsed["should_enter_top8"] = True
                parsed["new_fact_present"] = True
                parsed["importance_score"] = max(int(parsed.get("importance_score", 0)), 55)


    # Явные ценовые апдейты с числом не должны случайно выпадать из top
    if parsed.get("event_type") in ("price", "price_update"):
        if has_price or has_price_value or has_strong_number:
            if not parsed.get("repeat_without_new_detail", False):
                parsed["should_enter_top8"] = True
                parsed["new_fact_present"] = True
                parsed["importance_score"] = max(int(parsed.get("importance_score", 0)), 58)

    # Export/import flow stories с новыми цифрами тоже не должны выпадать
    if parsed.get("event_type") in ("export", "import"):
        if has_strong_number or high_value_flow:
            if not parsed.get("repeat_without_new_detail", False):
                parsed["should_enter_top8"] = True
                parsed["new_fact_present"] = True
                parsed["importance_score"] = max(int(parsed.get("importance_score", 0)), 55)

    # Слишком смелые выводы без цифр ослабляем
    if not has_price and not has_strong_number:
        exporter_relevance = parsed.get("exporter_relevance", "low")
        if exporter_relevance == "high":
            parsed["exporter_relevance"] = "medium"

    # Индексы без явного изменения цены не должны быть headline
    if "index" in text_blob and not has_price and not has_strong_number:
        parsed["importance_score"] = min(int(parsed.get("importance_score", 0)), 10)
        parsed["repeat_without_new_detail"] = True
        parsed["should_enter_top8"] = False
        parsed["new_fact_present"] = False

    # Страницы котировок/утренние сводки без конкретных цифр не должны попадать в итог
    weak_quote_markers = [
        "价格行情", "价格指数", "价格快讯", "晨讯", "早报", "午报", "日报",
        "港口现货价格", "市场价格", "市场行情", "spot prices", "daily index"
    ]
    if any(x in title.lower() for x in [m.lower() for m in weak_quote_markers]) and not has_price and not has_strong_number:
        parsed["importance_score"] = min(int(parsed.get("importance_score", 0)), 8)
        parsed["repeat_without_new_detail"] = True
        parsed["should_enter_top8"] = False
        parsed["new_fact_present"] = False

    # Если модель сама признает, что конкретных данных нет, режем материал
    weak_fact_markers = [
        "无具体", "缺乏具体", "未披露", "暂无具体", "no concrete", "no specific",
        "without details", "no figures", "no prices", "no transaction"
    ]
    headline_fact = str(parsed.get("headline_fact", "") or "").lower()
    what_happened = str(parsed.get("what_happened", "") or "").lower()
    if any(m in headline_fact or m in what_happened for m in [x.lower() for x in weak_fact_markers]) and not has_price and not has_strong_number:
        parsed["importance_score"] = min(int(parsed.get("importance_score", 0)), 6)
        parsed["repeat_without_new_detail"] = True
        parsed["should_enter_top8"] = False
        parsed["new_fact_present"] = False

    return parsed


def analyze_article(article):
    title = article.get("title", "")
    content = article.get("content", "")
    url = article.get("url", "")
    text_blob = f"{title}\n{content}".lower()

    is_china_safety = is_china_safety_event_text(text_blob)

    if any(x in text_blob for x in BLOCK_IN_FACTS) and not is_china_safety:
        return {
            "relevant_to_coal": False,
            "new_fact_present": False,
            "event_type": "other",
            "segment": "general",
            "region": "",
            "headline_fact": title,
            "what_happened": title,
            "importance_score": 0,
            "importance_reason": "Нерелевантный материал.",
            "price_impact_today": "неясно",
            "exporter_relevance": "low",
            "exporter_note": "",
            "is_repeat_theme": False,
            "repeat_without_new_detail": True,
            "should_enter_top8": False,
            "needs_context_in_summary": False,
            "has_numeric_price": False
        }

    response = client.responses.create(
        model="gpt-5.4-mini",
        input=build_fact_prompt(article)
    )

    raw = response.output_text.strip()
    parsed = extract_json_from_text(raw)

    if not parsed:
        seg = detect_coal_commodity(text_blob)
        parsed = {
            "relevant_to_coal": True,
            "new_fact_present": True,
            "event_type": "other",
            "segment": seg if seg else "general",
            "region": "",
            "headline_fact": title if title and title.lower() != "recommended articles" else "Новый материал по угольному рынку",
            "what_happened": title if title and title.lower() != "recommended articles" else "Опубликован новый материал по угольному рынку.",
            "importance_score": 40,
            "importance_reason": "fallback",
            "price_impact_today": "неясно",
            "exporter_relevance": "medium",
            "exporter_note": "",
            "is_repeat_theme": False,
            "repeat_without_new_detail": False,
            "should_enter_top8": True,
            "needs_context_in_summary": True,
            "has_numeric_price": False
        }

    m = re.search(r"(\d{2,6}(?:\.\d+)?)\s*(yuan|cny|usd|\$|元)", text_blob, re.I)
    if m:
        parsed["has_numeric_price"] = True
        parsed["price_value"] = m.group(1)
        cur = m.group(2).upper()
        if cur == "元":
            cur = "CNY"
        if cur == "$":
            cur = "USD"
        parsed["price_currency"] = cur
        parsed["price_unit"] = "/t"
        parsed["event_type"] = "price_update"
        parsed["importance_score"] = max(parsed.get("importance_score", 0), 60)

    if "/subject/" in url.lower() or "/zt/" in url.lower():
        parsed["new_fact_present"] = False
        parsed["repeat_without_new_detail"] = True
        parsed["should_enter_top8"] = False
        parsed["importance_score"] = 0

    if str(parsed.get("headline_fact", "")).strip().lower() == "recommended articles":
        parsed["headline_fact"] = str(parsed.get("what_happened", "")).split("。")[0][:120] or "Новый материал по угольному рынку"

    if is_china_safety:
        parsed["relevant_to_coal"] = True
        parsed["new_fact_present"] = True
        parsed["repeat_without_new_detail"] = False
        parsed["should_enter_top8"] = True
        if parsed.get("event_type") not in ("accident", "safety", "shutdown"):
            parsed["event_type"] = "safety"
        parsed["importance_score"] = max(int(parsed.get("importance_score", 0) or 0), 80)
        if parsed.get("exporter_relevance", "low") == "low":
            parsed["exporter_relevance"] = "medium"

    parsed = enforce_segment_consistency(article, parsed)
    parsed = _apply_post_rules(article, parsed)

    if is_china_safety:
        parsed["relevant_to_coal"] = True
        parsed["new_fact_present"] = True
        parsed["repeat_without_new_detail"] = False
        parsed["should_enter_top8"] = True
        if parsed.get("event_type") not in ("accident", "safety", "shutdown"):
            parsed["event_type"] = "safety"
        parsed["importance_score"] = max(int(parsed.get("importance_score", 0) or 0), 80)

    return parsed
