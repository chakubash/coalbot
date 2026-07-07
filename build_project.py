from pathlib import Path
import textwrap

FILES = {
    "config.py": '''
from zoneinfo import ZoneInfo

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = "7809564417:AAH_xrb1ZzkqEd7_9ml4JZImBuqO6G1QCG4"
PRIMARY_TELEGRAM_CHAT_ID = ""

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

DATA_DIR = "data_runs"
DATA_STATE_DIR = "data"

STATE_FILE = f"{DATA_STATE_DIR}/state.json"
SUBSCRIBERS_FILE = f"{DATA_STATE_DIR}/subscribers.json"
EVENT_MEMORY_FILE = f"{DATA_STATE_DIR}/event_memory.json"
CACHE_FILE = f"{DATA_STATE_DIR}/cache.json"

MYSTEEL_GLOBAL_URL = "https://www.mysteel.net/market-insights/news/latest/"
MYSTEEL_FAST_URL = "https://www.mysteel.com/fastcomment/#/"
MYSTEEL_CN_LIST_TEMPLATE = "https://list1.mysteel.com/article/p-318,355-------------{}.html?keyWord="
SXCOAL_NEWS_URL = "https://www.sxcoal.com/en/news"
CLS_COAL_URL = "https://www.cls.cn/subject/1503"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

KEYWORDS = [
    "coal", "coking coal", "thermal coal", "coke",
    "coal mine", "mine accident", "coal output", "coal price",
    "coal inventory", "coal imports", "coal export",
    "imported coking coal", "seaborne coking coal", "seaborne thermal coal",
    "port", "railway", "rail", "shutdown", "inspection", "safety",
    "production cut", "supply", "steel mill", "blast furnace",
    "power plant", "electricity", "coke plant", "metallurgical coal",
    "freight", "domestic coal", "coal market",
    "煤", "焦煤", "焦炭", "动力煤", "炼焦煤", "煤矿", "港口", "库存",
    "铁路", "运价", "事故", "停产", "安全检查", "进口煤", "出口煤",
    "电厂", "钢厂", "高炉", "焦化", "秦皇岛", "曹妃甸", "黄骅", "日耗", "开工"
]

PRICE_KEYWORDS = [
    "price", "prices", "pricing", "quote", "quoted", "quotation",
    "index", "assessment", "offer", "bid", "premium", "discount",
    "cnf", "fob", "cfr", "spot",
    "港口报价", "报价", "现货价", "价格上涨", "价格下跌",
    "价格上调", "价格下调", "指数", "成交价", "到岸价", "离岸价",
    "进口煤价格", "焦煤价格", "动力煤价格", "焦炭价格"
]

EXCLUDE = [
    "soybean", "lithium", "nickel", "stainless", "battery", "electrolyte",
    "lng", "refined oil", "new energy", "solar", "photovoltaic",
    "polypropylene", "pp", "iron ore", "aluminum", "copper", "zinc",
    "tin", "lead", "manganese", "silicon"
]
''',

    "models.py": '''
from dataclasses import dataclass
from typing import Optional


@dataclass
class ArticleCandidate:
    source: str
    title: str
    url: str
    context_text: str = ""
    list_published_at: Optional[str] = None


@dataclass
class Article:
    source: str
    title: str
    url: str
    content: str
    published_at: Optional[str]
    language: str
    raw_html: str = ""
    published_at_raw: str = ""
''',

    "storage.py": '''
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
            f.write(json.dumps(row, ensure_ascii=False) + "\\n")


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
''',

    "utils.py": '''
import hashlib
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import HEADERS, KEYWORDS, PRICE_KEYWORDS, EXCLUDE, BEIJING_TZ


def clean_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def md5_text(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def normalize_title(title: str) -> str:
    t = clean_text(title).lower()
    t = re.sub(r"[^\\w\\u4e00-\\u9fff\\s]", " ", t)
    t = re.sub(r"\\s+", " ", t).strip()
    return t


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def is_coal_related(text: str) -> bool:
    low = (text or "").lower()
    if any(bad in low for bad in EXCLUDE):
        return False
    return any(k.lower() in low for k in KEYWORDS)


def is_price_event_text(text: str) -> bool:
    low = (text or "").lower()
    return any(k.lower() in low for k in PRICE_KEYWORDS)


def fetch_html(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def soup_from_url(url: str) -> Optional[BeautifulSoup]:
    html = fetch_html(url)
    if not html:
        return None
    return BeautifulSoup(html, "html.parser")


def parse_dt_from_text(text: str) -> Optional[datetime]:
    if not text:
        return None

    text = clean_text(text)

    month_map = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
        "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
    }

    patterns = [
        ("en_mon", r"\\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\s+(\\d{1,2}),\\s*(\\d{4})\\s+(\\d{2}):(\\d{2})\\b"),
        ("dash", r"\\b(\\d{4})-(\\d{2})-(\\d{2})\\s+(\\d{2}):(\\d{2})\\b"),
        ("slash", r"\\b(\\d{4})/(\\d{2})/(\\d{2})\\s+(\\d{2}):(\\d{2})\\b"),
        ("cn_full", r"\\b(\\d{4})年(\\d{1,2})月(\\d{1,2})日\\s*(\\d{1,2}):(\\d{2})\\b"),
        ("short_md", r"\\b(\\d{1,2})-(\\d{1,2})\\s+(\\d{2}):(\\d{2})\\b"),
        ("time_only", r"\\b(\\d{2}):(\\d{2})\\b"),
    ]

    for kind, pattern in patterns:
        m = re.search(pattern, text)
        if not m:
            continue

        if kind == "en_mon":
            return datetime(
                int(m.group(3)), month_map[m.group(1)], int(m.group(2)),
                int(m.group(4)), int(m.group(5)), tzinfo=BEIJING_TZ
            )

        if kind == "dash":
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)), int(m.group(5)), tzinfo=BEIJING_TZ
            )

        if kind == "slash":
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)), int(m.group(5)), tzinfo=BEIJING_TZ
            )

        if kind == "cn_full":
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)), int(m.group(5)), tzinfo=BEIJING_TZ
            )

        if kind == "short_md":
            now = datetime.now(BEIJING_TZ)
            return datetime(
                now.year, int(m.group(1)), int(m.group(2)),
                int(m.group(3)), int(m.group(4)), tzinfo=BEIJING_TZ
            )

        if kind == "time_only":
            now = datetime.now(BEIJING_TZ)
            return datetime(
                now.year, now.month, now.day,
                int(m.group(1)), int(m.group(2)), tzinfo=BEIJING_TZ
            )

    return None


def extract_context_block_text(a_tag):
    node = a_tag
    for _ in range(3):
        if node and node.parent:
            node = node.parent
    return clean_text(node.get_text(" ", strip=True))[:1500] if node else ""


def extract_main_content_from_soup(soup: BeautifulSoup):
    selectors = [
        "div.article-content",
        "div.article_content",
        "div.content",
        "div.news-content",
        "div.news_content",
        "div#article_content",
        "div#content",
        "div.detail-content",
        "div.detail_content",
        "div.txt-content",
        "div.text",
        "div.article",
        "article",
    ]

    for sel in selectors:
        block = soup.select_one(sel)
        if block:
            text = clean_text(block.get_text("\\n", strip=True))
            if len(text) >= 200:
                return text[:7000]

    paragraphs = []
    for p in soup.find_all("p"):
        t = clean_text(p.get_text(" ", strip=True))
        if len(t) >= 40:
            paragraphs.append(t)

    if paragraphs:
        return "\\n".join(paragraphs[:30])[:7000]

    return clean_text(soup.get_text(" ", strip=True))[:5000]


def fetch_article_details_common(item):
    html = fetch_html(item["url"])
    fallback_title = item["title"]
    context_text = item.get("context_text", "")
    fallback_dt = parse_dt_from_text(item.get("list_published_at", "") or "")
    source = item["source"]

    if not html:
        return {
            "source": source,
            "title": fallback_title,
            "url": item["url"],
            "content": "",
            "published_at": fallback_dt.strftime("%Y-%m-%d %H:%M") if fallback_dt else None,
            "language": "zh" if re.search(r"[\\u4e00-\\u9fff]", fallback_title) else "en",
            "raw_html": "",
            "published_at_raw": "",
        }

    soup = BeautifulSoup(html, "html.parser")

    title = fallback_title
    for tag in ["h1", "h2", "title"]:
        el = soup.find(tag)
        if el:
            candidate = clean_text(el.get_text(" ", strip=True))
            if len(candidate) > 8:
                title = candidate
                break

    content = extract_main_content_from_soup(soup)
    page_text = clean_text(soup.get_text(" ", strip=True))

    published_dt = None
    published_raw = ""
    candidate_texts = [page_text[:4000], content[:3000], context_text]

    for candidate in candidate_texts:
        dt = parse_dt_from_text(candidate)
        if dt:
            published_dt = dt
            published_raw = candidate[:300]
            break

    if not published_dt and fallback_dt:
        published_dt = fallback_dt
        published_raw = fallback_dt.strftime("%Y-%m-%d %H:%M")

    lang = "zh" if re.search(r"[\\u4e00-\\u9fff]", f"{title} {content}") else "en"

    return {
        "source": source,
        "title": title,
        "url": item["url"],
        "content": content,
        "published_at": published_dt.strftime("%Y-%m-%d %H:%M") if published_dt else None,
        "language": lang,
        "raw_html": html[:15000],
        "published_at_raw": published_raw,
    }
''',

    "fx.py": '''
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from config import BEIJING_TZ

_fx_cache = {"updated_at": None, "cny_to_usd": None}


def fetch_ecb_rates():
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        rates = {}
        for elem in root.iter():
            currency = elem.attrib.get("currency")
            rate = elem.attrib.get("rate")
            if currency and rate:
                rates[currency] = float(rate)
        return rates
    except Exception:
        return {}


def cny_to_usd_rate():
    global _fx_cache
    now = datetime.now(BEIJING_TZ)

    if _fx_cache["updated_at"] and _fx_cache["cny_to_usd"] is not None:
        if now - _fx_cache["updated_at"] < timedelta(hours=6):
            return _fx_cache["cny_to_usd"]

    rates = fetch_ecb_rates()
    eur_usd = rates.get("USD")
    eur_cny = rates.get("CNY")
    if not eur_usd or not eur_cny:
        return _fx_cache["cny_to_usd"]

    rate = eur_usd / eur_cny
    _fx_cache["updated_at"] = now
    _fx_cache["cny_to_usd"] = rate
    return rate


def format_price_with_usd(value, currency, unit=""):
    try:
        numeric_value = float(str(value).replace(",", ""))
    except Exception:
        return f"{value} {currency}{unit}"

    currency = (currency or "").upper()

    if currency == "CNY":
        rate = cny_to_usd_rate()
        if rate:
            usd_value = numeric_value * rate
            return f"{numeric_value:.2f} CNY{unit} (≈ {usd_value:.2f} USD{unit})"
        return f"{numeric_value:.2f} CNY{unit}"

    if currency in ["USD", "$"]:
        return f"{numeric_value:.2f} USD{unit}"

    return f"{numeric_value:.2f} {currency}{unit}"
''',

    "prompts.py": '''
def build_fact_prompt(article):
    return f"""
Ты — старший аналитик рынка угля.

Разбери одну новость. Верни только JSON, без пояснений и без markdown.

Задача:
1. понять, относится ли новость к углю;
2. выделить главный новый факт;
3. определить, насколько это важно именно сейчас;
4. определить, важно ли это для российского экспортёра угля в Китай;
5. отличить:
   - новую цену/котировку,
   - новый факт по аварии/остановке/безопасности,
   - логистику/порты/жд,
   - импорт/экспорт,
   - спрос steel mills / coke plants / power plants,
   - старую повторяющуюся тему без нового факта.

Верни JSON строго такого вида:

{{
  "relevant_to_coal": true,
  "new_fact_present": true,
  "event_type": "price|price_update|accident|shutdown|safety|logistics|port|rail|import|export|inventory|demand|supply|policy|capital_market|other",
  "segment": "coking_coal|thermal_coal|coke|general",
  "region": "string",
  "headline_fact": "короткий факт на русском",
  "what_happened": "2-3 предложения на русском, без воды",
  "importance_score": 0,
  "importance_reason": "коротко на русском",
  "price_impact_today": "рост|снижение|ограниченно|неясно",
  "exporter_relevance": "high|medium|low",
  "exporter_note": "кратко на русском",
  "is_repeat_theme": false,
  "repeat_without_new_detail": false,
  "should_enter_top8": true,
  "needs_context_in_summary": true,
  "has_numeric_price": false,
  "price_value": null,
  "price_currency": "",
  "price_unit": "",
  "price_type": "benchmark|spot|offer|trade|index|port_quote|unknown"
}}

Правила оценки importance_score:
- 90-100: авария на шахте, остановка добычи, проверка безопасности с риском снижения предложения, резкий новый ценовой сдвиг, серьёзный сбой порта/жд/импорта
- 70-89: новые подтверждённые цены/котировки по важному сегменту, новые данные по запасам/импорту/спросу, которые реально меняют картину
- 40-69: умеренно важный рыночный апдейт
- 0-39: слабая новость, комментарий, повтор старой темы без нового факта

Если новость содержит новую котировку, индекс, цену, bid/offer, портовую цену, импортную цену, оценку рынка или ценовой апдейт по углю — это надо классифицировать как "price_update", а не как "other".

Если в новости есть новая цена, котировка, индекс, оффер, портовая报价 или уровень сделки, ты обязан:
1. заполнить поля has_numeric_price, price_value, price_currency, price_unit, price_type;
2. не пропускать цифру;
3. если цена в юанях, это особенно важно для финальной сводки.

Если тема старая и в новости нет нового значимого факта, поставь:
"is_repeat_theme": true,
"repeat_without_new_detail": true,
и снизь importance_score.

Новость:
Источник: {article['source']}
Заголовок: {article['title']}
Время публикации: {article['published_at']}
Текст:
{article['content']}
"""


def build_report_prompt(event_blocks: str, today_str: str, start_str: str, end_str: str):
    return f"""
Ты — главный аналитик и служба мониторинга угольного рынка.

Твоя задача — написать качественную, плотную, профессиональную сводку сначала на русском языке, а затем дать эту же сводку на китайском языке в очень качественном деловом переводе.

Тебе даны уже отобранные и ранжированные события.
Сначала хорошо их осмысли, сопоставь, убери повторы и только потом пиши итог.
Скорость не важна. Важна точность, логика, нормальный язык и отсутствие мусора.

Период обзора:
{today_str}, {start_str}–{end_str} по пекинскому времени.

Жёсткие требования к русской части:
- пиши только хорошим русским языком;
- нельзя писать как машинный перевод;
- нельзя писать канцеляритом;
- нельзя писать воду;
- нельзя повторять одну и ту же мысль разными словами;
- нельзя использовать слова mixed, bullish, bearish, neutral, драйвер, сентимент, апсайд, даунсайд;
- если есть авария, остановка шахты, новая цена, новый портовый ориентир, логистический сбой, импортный сдвиг — это должно быть в первых пунктах;
- угольные акции можно включать, но только если они реально отражают важный рыночный сигнал;
- не надо делать пункты слишком короткими: в каждом пункте должно быть понятно, что именно произошло и почему это важно;
- но и длинных абзацев не нужно;
- максимум 8 пунктов;
- если новых сильных событий меньше, не надо раздувать до 8;
- если тема старая и без нового факта, не поднимай её наверх;
- если есть новые цены/котировки, называй их прямо;
- если цена указана в юанях, в русской версии рядом обязательно укажи эквивалент в долларах США в скобках;
- нельзя писать "цены выросли" без конкретной новой цифры, если цифра есть в данных;
- различай: цена, сделки, офферы, запасы, логистика, аварии, спрос, акции.

Требования к китайской части:
- это должен быть качественный деловой китайский язык;
- не дословный кривой перевод;
- смысл должен полностью совпадать с русской частью;
- структура должна быть такой же;
- язык должен быть естественным для деловой аналитической записки;
- цифры и валюты должны быть сохранены полностью.

Верни строго JSON такого вида:

{{
  "ru": "полная сводка на русском",
  "zh": "这同一份摘要的完整中文版本"
}}

Русская структура внутри поля "ru" строго такая:

Период обзора:
— ...

7–8 главных событий за период:
1) ...
2) ...
3) ...
4) ...
5) ...
6) ...
7) ...
8) ...

Что это значит:
— ...
— ...
— ...

Общая картина рынка:
— ...
— ...

Вывод:
— ...
— ...
— ...

Китайская структура внутри поля "zh" строго такая:

观察区间：
— ...

本时段7–8个重点事件：
1）...
2）...
3）...
4）...
5）...
6）...
7）...
8）...

这意味着：
— ...
— ...
— ...

当前市场整体情况：
— ...
— ...

结论：
— ...
— ...
— ...

События:
{event_blocks}
"""
''',

    "sources/__init__.py": '''
from .mysteel_global import collect_links as collect_mysteel_global_links
from .mysteel_fast import collect_links as collect_mysteel_fast_links
from .mysteel_cn_list import collect_links as collect_mysteel_cn_list_links
from .sxcoal import collect_links as collect_sxcoal_links
from .cls import collect_links as collect_cls_links
from utils import fetch_article_details_common


def collect_all_candidates():
    rows = []
    rows.extend(collect_mysteel_global_links())
    rows.extend(collect_mysteel_cn_list_links())
    rows.extend(collect_sxcoal_links())
    rows.extend(collect_cls_links())
    rows.extend(collect_mysteel_fast_links())
    return rows


def fetch_article_details_by_source(item):
    return fetch_article_details_common(item)
''',

    "sources/mysteel_global.py": '''
from urllib.parse import urljoin
from models import ArticleCandidate
from config import MYSTEEL_GLOBAL_URL
from utils import soup_from_url, clean_text, is_coal_related, md5_text, extract_context_block_text, parse_dt_from_text


def collect_links():
    soup = soup_from_url(MYSTEEL_GLOBAL_URL)
    if not soup:
        return []

    results = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = clean_text(a.get_text(" ", strip=True))
        href = a["href"].strip()

        if not title or len(title) < 18:
            continue
        if not is_coal_related(title):
            continue

        full_url = urljoin("https://www.mysteel.net", href)
        key = md5_text(title + full_url)
        if key in seen:
            continue
        seen.add(key)

        context_text = extract_context_block_text(a)
        list_dt = parse_dt_from_text(context_text)

        results.append(ArticleCandidate(
            source="mysteel_global",
            title=title,
            url=full_url,
            context_text=context_text,
            list_published_at=list_dt.strftime("%Y-%m-%d %H:%M") if list_dt else None,
        ).__dict__)

    return results
''',

    "sources/mysteel_cn_list.py": '''
import time
from urllib.parse import urljoin
from models import ArticleCandidate
from config import MYSTEEL_CN_LIST_TEMPLATE
from utils import soup_from_url, clean_text, is_coal_related, md5_text, extract_context_block_text, parse_dt_from_text


def collect_links(max_pages: int = 8):
    results = []
    seen = set()

    for page in range(1, max_pages + 1):
        soup = soup_from_url(MYSTEEL_CN_LIST_TEMPLATE.format(page))
        if not soup:
            continue

        page_found = 0
        for a in soup.find_all("a", href=True):
            title = clean_text(a.get_text(" ", strip=True))
            href = a["href"].strip()

            if not title or len(title) < 8:
                continue
            if not is_coal_related(title):
                continue

            full_url = urljoin("https://list1.mysteel.com", href)
            key = md5_text(title + full_url)
            if key in seen:
                continue
            seen.add(key)

            context_text = extract_context_block_text(a)
            list_dt = parse_dt_from_text(context_text)

            results.append(ArticleCandidate(
                source="mysteel_cn_list",
                title=title,
                url=full_url,
                context_text=context_text,
                list_published_at=list_dt.strftime("%Y-%m-%d %H:%M") if list_dt else None,
            ).__dict__)
            page_found += 1

        if page_found == 0:
            break

        time.sleep(0.5)

    return results
''',

    "sources/sxcoal.py": '''
import time
from urllib.parse import urljoin
from models import ArticleCandidate
from config import SXCOAL_NEWS_URL
from utils import soup_from_url, clean_text, is_coal_related, md5_text, extract_context_block_text, parse_dt_from_text


def collect_links(max_pages: int = 5):
    results = []
    seen = set()

    urls = [SXCOAL_NEWS_URL]
    for p in range(2, max_pages + 1):
        urls.append(f"{SXCOAL_NEWS_URL}?page={p}")

    for url in urls:
        soup = soup_from_url(url)
        if not soup:
            continue

        found = 0
        for a in soup.find_all("a", href=True):
            title = clean_text(a.get_text(" ", strip=True))
            href = a["href"].strip()

            if not title or len(title) < 15:
                continue
            if not is_coal_related(title):
                continue

            full_url = urljoin("https://www.sxcoal.com", href)
            key = md5_text(title + full_url)
            if key in seen:
                continue
            seen.add(key)

            context_text = extract_context_block_text(a)
            list_dt = parse_dt_from_text(context_text)

            results.append(ArticleCandidate(
                source="sxcoal",
                title=title,
                url=full_url,
                context_text=context_text,
                list_published_at=list_dt.strftime("%Y-%m-%d %H:%M") if list_dt else None,
            ).__dict__)
            found += 1

        if found == 0 and url != SXCOAL_NEWS_URL:
            break

        time.sleep(0.5)

    return results
''',

    "sources/cls.py": '''
import time
from urllib.parse import urljoin
from models import ArticleCandidate
from config import CLS_COAL_URL
from utils import soup_from_url, clean_text, is_coal_related, md5_text, extract_context_block_text, parse_dt_from_text


def collect_links(max_pages: int = 4):
    results = []
    seen = set()

    urls = [CLS_COAL_URL]
    for p in range(2, max_pages + 1):
        urls.append(f"{CLS_COAL_URL}?page={p}")

    for url in urls:
        soup = soup_from_url(url)
        if not soup:
            continue

        found = 0
        for a in soup.find_all("a", href=True):
            title = clean_text(a.get_text(" ", strip=True))
            href = a["href"].strip()

            if not title or len(title) < 8:
                continue
            if not is_coal_related(title):
                continue

            full_url = urljoin("https://www.cls.cn", href)
            key = md5_text(title + full_url)
            if key in seen:
                continue
            seen.add(key)

            context_text = extract_context_block_text(a)
            list_dt = parse_dt_from_text(context_text)

            results.append(ArticleCandidate(
                source="cls",
                title=title,
                url=full_url,
                context_text=context_text,
                list_published_at=list_dt.strftime("%Y-%m-%d %H:%M") if list_dt else None,
            ).__dict__)
            found += 1

        if found == 0 and url != CLS_COAL_URL:
            break

        time.sleep(0.5)

    return results
''',

    "sources/mysteel_fast.py": '''
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from models import ArticleCandidate
from config import MYSTEEL_FAST_URL
from utils import clean_text, is_coal_related, md5_text, extract_context_block_text, parse_dt_from_text


def collect_links(max_items: int = 120):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []

    results = []
    seen = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(MYSTEEL_FAST_URL, wait_until="networkidle", timeout=120000)

            import time
            time.sleep(3)

            for _ in range(8):
                page.mouse.wheel(0, 4000)
                time.sleep(1.2)

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):
            title = clean_text(a.get_text(" ", strip=True))
            href = a["href"].strip()

            if not title or len(title) < 6:
                continue
            if not is_coal_related(title):
                continue

            full_url = urljoin("https://www.mysteel.com", href)
            key = md5_text(title + full_url)
            if key in seen:
                continue
            seen.add(key)

            context_text = extract_context_block_text(a)
            list_dt = parse_dt_from_text(context_text)

            results.append(ArticleCandidate(
                source="mysteel_fast",
                title=title,
                url=full_url,
                context_text=context_text,
                list_published_at=list_dt.strftime("%Y-%m-%d %H:%M") if list_dt else None,
            ).__dict__)

            if len(results) >= max_items:
                break

    except Exception:
        return []

    return results
''',

    "pipeline/__init__.py": '''
''',

    "pipeline/normalize.py": '''
from sources import fetch_article_details_by_source
from storage import save_jsonl
from utils import is_coal_related, normalize_title, parse_dt_from_text


def normalize_and_fetch_details(candidates, start_dt, end_dt):
    normalized = []
    skipped = []

    for item in candidates:
        article = fetch_article_details_by_source(item)

        full_text_for_filter = f"{article['title']} {article['content']}"
        if not is_coal_related(full_text_for_filter):
            skipped.append({
                "reason": "not_coal_related",
                "source": item["source"],
                "title": item["title"],
                "url": item["url"],
            })
            continue

        if not article["published_at"]:
            skipped.append({
                "reason": "no_published_at",
                "source": item["source"],
                "title": article["title"],
                "url": article["url"],
                "published_at_raw": article.get("published_at_raw", ""),
            })
            continue

        dt = parse_dt_from_text(article["published_at"])
        if not dt:
            skipped.append({
                "reason": "cannot_parse_datetime",
                "source": item["source"],
                "title": article["title"],
                "url": article["url"],
                "published_at": article["published_at"],
            })
            continue

        if not (start_dt <= dt < end_dt):
            skipped.append({
                "reason": "outside_window",
                "source": item["source"],
                "title": article["title"],
                "url": article["url"],
                "published_at": article["published_at"],
            })
            continue

        normalized.append({
            "source": article["source"],
            "title": article["title"],
            "url": article["url"],
            "content": article["content"],
            "published_at": article["published_at"],
            "language": article["language"],
            "title_norm": normalize_title(article["title"]),
            "published_at_raw": article.get("published_at_raw", ""),
        })

    return normalized, skipped
''',

    "pipeline/dedup.py": '''
from utils import md5_text, similarity


def dedupe_articles(articles):
    exact_seen = set()
    exact_pass = []

    for art in articles:
        key = md5_text((art["url"] or "") + "|" + (art["title_norm"] or ""))
        if key in exact_seen:
            continue
        exact_seen.add(key)
        exact_pass.append(art)

    deduped = []
    for art in exact_pass:
        duplicate = False
        for kept in deduped:
            same_title = similarity(art["title"], kept["title"]) >= 0.92
            same_time = art["published_at"] == kept["published_at"]
            if same_title and same_time:
                duplicate = True
                break
        if not duplicate:
            deduped.append(art)

    return deduped
''',

    "pipeline/facts.py": '''
import json
import re
from openai import OpenAI
from config import OPENAI_API_KEY
from prompts import build_fact_prompt

client = OpenAI(api_key=OPENAI_API_KEY)


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


def analyze_article(article):
    response = client.responses.create(
        model="gpt-5.4-mini",
        input=build_fact_prompt(article)
    )

    raw = response.output_text.strip()
    parsed = extract_json_from_text(raw)

    if not parsed:
        parsed = {
            "relevant_to_coal": True,
            "new_fact_present": True,
            "event_type": "other",
            "segment": "general",
            "region": "",
            "headline_fact": article["title"],
            "what_happened": article["title"],
            "importance_score": 30,
            "importance_reason": "Не удалось корректно разобрать новость в JSON.",
            "price_impact_today": "неясно",
            "exporter_relevance": "low",
            "exporter_note": "",
            "is_repeat_theme": False,
            "repeat_without_new_detail": False,
            "should_enter_top8": True,
            "needs_context_in_summary": True,
            "has_numeric_price": False,
            "price_value": None,
            "price_currency": "",
            "price_unit": "",
            "price_type": "unknown",
        }

    if parsed and not parsed.get("has_numeric_price"):
        text_blob = f"{article.get('title', '')} {article.get('content', '')}"

        price_patterns = [
            r"(\\d{2,6}(?:\\.\\d+)?)\\s*(yuan|cny|元)(?:\\s*/\\s*(t|ton|吨))?",
            r"(\\d{2,6}(?:\\.\\d+)?)\\s*(usd|\\$)(?:\\s*/\\s*(t|ton))?",
        ]

        found = None
        for pat in price_patterns:
            m = re.search(pat, text_blob, flags=re.IGNORECASE)
            if m:
                found = m
                break

        if found:
            parsed["has_numeric_price"] = True
            parsed["price_value"] = found.group(1)

            cur = found.group(2).upper()
            if cur == "元":
                cur = "CNY"
            if cur == "$":
                cur = "USD"

            parsed["price_currency"] = cur

            unit = found.group(3) if len(found.groups()) >= 3 else ""
            if unit:
                unit = unit.lower()
                if unit in ["t", "ton", "吨"]:
                    unit = "/t"
            else:
                unit = ""

            parsed["price_unit"] = unit
            if parsed.get("event_type") == "other":
                parsed["event_type"] = "price_update"

    return parsed
''',

    "pipeline/scoring.py": '''
from datetime import datetime, timedelta
from config import BEIJING_TZ
from storage import load_event_memory, save_event_memory
from utils import md5_text, is_price_event_text


def event_fingerprint(analysis: dict):
    base = (
        str(analysis.get("event_type", "")) + "|" +
        str(analysis.get("segment", "")) + "|" +
        str(analysis.get("region", "")) + "|" +
        str(analysis.get("headline_fact", ""))
    )
    return md5_text(base.lower())


def is_old_repeat(analysis: dict, days: int = 5):
    memory = load_event_memory()
    now = datetime.now(BEIJING_TZ)
    fp = event_fingerprint(analysis)

    for item in memory.get("events", []):
        if item.get("fingerprint") != fp:
            continue
        try:
            dt = datetime.strptime(item["seen_at"], "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING_TZ)
        except Exception:
            continue
        if now - dt <= timedelta(days=days):
            return True
    return False


def remember_events(analyzed_events: list):
    memory = load_event_memory()
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")

    for ev in analyzed_events:
        memory["events"].append({
            "fingerprint": event_fingerprint(ev["analysis"]),
            "seen_at": now_str,
            "headline_fact": ev["analysis"].get("headline_fact", "")
        })

    memory["events"] = memory["events"][-500:]
    save_event_memory(memory)


def score_event(analysis: dict, article: dict = None):
    score = int(analysis.get("importance_score", 0))

    event_type = analysis.get("event_type", "")
    exporter_relevance = analysis.get("exporter_relevance", "low")
    repeat_without_new_detail = analysis.get("repeat_without_new_detail", False)

    combined_text = ""
    if article:
        combined_text = f"{article.get('title', '')} {article.get('content', '')}"

    if event_type in ["accident", "shutdown", "safety"]:
        score += 25

    if event_type in ["price", "price_update"]:
        score += 20

    if is_price_event_text(combined_text):
        score += 15

    if event_type in ["port", "rail", "logistics", "import", "export"]:
        score += 12

    if event_type in ["inventory", "demand", "supply"]:
        score += 8

    if event_type == "capital_market":
        score += 3

    if exporter_relevance == "high":
        score += 10
    elif exporter_relevance == "medium":
        score += 5

    if repeat_without_new_detail:
        score -= 35

    if is_old_repeat(analysis):
        score -= 20

    if analysis.get("should_enter_top8") is False:
        score -= 15

    return max(0, min(score, 100))
''',

    "pipeline/clustering.py": '''
def cluster_top_rows(rows, max_items=8):
    # Первая итерация: просто возвращаем top rows.
    # Потом сюда можно добавить настоящую кластеризацию.
    return rows[:max_items]
''',

    "pipeline/reports.py": '''
import os
from datetime import datetime

from openai import OpenAI

from config import OPENAI_API_KEY, BEIJING_TZ
from fx import format_price_with_usd
from prompts import build_report_prompt
from storage import save_jsonl
from pipeline.facts import analyze_article, extract_json_from_text
from pipeline.scoring import score_event, remember_events
from pipeline.clustering import cluster_top_rows

client = OpenAI(api_key=OPENAI_API_KEY)


def build_bilingual_summary_for_range(articles, previous_summary_ru, start_dt, end_dt, run_dir):
    start_str = start_dt.strftime("%H:%M")
    end_str = end_dt.strftime("%H:%M")
    today_str = start_dt.strftime("%Y-%m-%d")

    if not articles:
        ru_summary = (
            f"Период обзора:\\n"
            f"— {today_str}, {start_str}–{end_str} по Пекину.\\n\\n"
            "7–8 главных событий за период:\\n"
            "1) Новых значимых событий по угольному рынку за этот период не выявлено.\\n\\n"
            "Что это значит:\\n"
            "— Новостной фон существенно не изменился.\\n\\n"
            "Общая картина рынка:\\n"
            "— Рынок остаётся в прежнем состоянии без нового сильного сигнала по ценам, логистике или предложению.\\n\\n"
            "Вывод:\\n"
            "— Новых факторов, требующих менять ценовые ориентиры или переговорную позицию прямо сейчас, не появилось."
        )

        zh_summary = (
            f"观察区间：\\n"
            f"— 北京时间 {today_str} {start_str}–{end_str}。\\n\\n"
            "本时段7–8个重点事件：\\n"
            "1）本时段煤炭市场未出现新的重要事件。\\n\\n"
            "这意味着：\\n"
            "— 新闻面整体变化不大。\\n\\n"
            "当前市场整体情况：\\n"
            "— 市场仍维持原有格局，价格、物流和供应端均未出现新的强信号。\\n\\n"
            "结论：\\n"
            "— 暂未出现需要立即调整报价或谈判策略的新因素。"
        )

        with open(os.path.join(run_dir, "final_summary_ru.txt"), "w", encoding="utf-8") as f:
            f.write(ru_summary)
        with open(os.path.join(run_dir, "final_summary_zh.txt"), "w", encoding="utf-8") as f:
            f.write(zh_summary)
        return {"ru": ru_summary, "zh": zh_summary}

    analyzed_rows = []
    for article in articles:
        analysis = analyze_article(article)
        final_score = score_event(analysis, article)

        analyzed_rows.append({
            "article": article,
            "analysis": analysis,
            "final_score": final_score,
        })

    save_jsonl(
        os.path.join(run_dir, "analyzed_articles.jsonl"),
        [
            {
                "source": row["article"]["source"],
                "title": row["article"]["title"],
                "url": row["article"]["url"],
                "published_at": row["article"]["published_at"],
                "analysis": row["analysis"],
                "final_score": row["final_score"],
            }
            for row in analyzed_rows
        ]
    )

    filtered = []
    for row in analyzed_rows:
        a = row["analysis"]
        if not a.get("relevant_to_coal", True):
            continue
        if row["final_score"] < 35:
            continue
        filtered.append(row)

    filtered.sort(key=lambda x: x["final_score"], reverse=True)
    top_rows = cluster_top_rows(filtered, max_items=8)

    if not top_rows:
        ru_summary = (
            f"Период обзора:\\n"
            f"— {today_str}, {start_str}–{end_str} по Пекину.\\n\\n"
            "7–8 главных событий за период:\\n"
            "1) В потоке были новости по угольной теме, но новых сильных фактов, меняющих картину рынка прямо сейчас, за этот период не появилось.\\n\\n"
            "Что это значит:\\n"
            "— Рынок живёт в рамках уже известных тем без нового сильного сигнала.\\n\\n"
            "Общая картина рынка:\\n"
            "— Резкого изменения баланса спроса и предложения, логистики или импортной конъюнктуры за период не видно.\\n\\n"
            "Вывод:\\n"
            "— Новых оснований резко менять переговорную позицию на текущий момент нет."
        )

        zh_summary = (
            f"观察区间：\\n"
            f"— 北京时间 {today_str} {start_str}–{end_str}。\\n\\n"
            "本时段7–8个重点事件：\\n"
            "1）本时段虽有涉煤新闻，但没有出现足以改变当前市场格局的新强信号。\\n\\n"
            "这意味着：\\n"
            "— 市场仍在围绕已知主题运行，暂未出现新的强驱动。\\n\\n"
            "当前市场整体情况：\\n"
            "— 供需、物流与进口环境在本时段内没有发生明显变化。\\n\\n"
            "结论：\\n"
            "— 当前尚无充分理由大幅调整谈判策略。"
        )

        with open(os.path.join(run_dir, "final_summary_ru.txt"), "w", encoding="utf-8") as f:
            f.write(ru_summary)
        with open(os.path.join(run_dir, "final_summary_zh.txt"), "w", encoding="utf-8") as f:
            f.write(zh_summary)
        return {"ru": ru_summary, "zh": zh_summary}

    remember_events(top_rows)

    event_blocks = []
    for i, row in enumerate(top_rows, 1):
        a = row["analysis"]

        formatted_price = ""
        if a.get("has_numeric_price") and a.get("price_value") and a.get("price_currency"):
            formatted_price = format_price_with_usd(
                a.get("price_value"),
                a.get("price_currency"),
                a.get("price_unit", "")
            )

        event_blocks.append(
            f"СОБЫТИЕ {i}\\n"
            f"Источник: {row['article']['source']}\\n"
            f"Время: {row['article']['published_at']}\\n"
            f"Заголовок: {row['article']['title']}\\n"
            f"Факт: {a.get('headline_fact', '')}\\n"
            f"Что произошло: {a.get('what_happened', '')}\\n"
            f"Цена: {formatted_price}\\n"
            f"Тип цены: {a.get('price_type', '')}\\n"
            f"Тип события: {a.get('event_type', '')}\\n"
            f"Сегмент: {a.get('segment', '')}\\n"
            f"Регион: {a.get('region', '')}\\n"
            f"Влияние на цену сегодня: {a.get('price_impact_today', '')}\\n"
            f"Значение для экспортёра: {a.get('exporter_note', '')}\\n"
            f"Скоринг: {row['final_score']}\\n"
            f"Ссылка: {row['article']['url']}"
        )

    response = client.responses.create(
        model="gpt-5.4",
        input=build_report_prompt("\\n\\n".join(event_blocks), today_str, start_str, end_str)
    )

    raw = response.output_text.strip()
    parsed = extract_json_from_text(raw)

    if not parsed or "ru" not in parsed or "zh" not in parsed:
        ru_summary = raw
        zh_summary = "未能自动生成中文版本，请检查模型输出。"
    else:
        ru_summary = parsed["ru"].strip()
        zh_summary = parsed["zh"].strip()

    with open(os.path.join(run_dir, "final_summary_ru.txt"), "w", encoding="utf-8") as f:
        f.write(ru_summary)
    with open(os.path.join(run_dir, "final_summary_zh.txt"), "w", encoding="utf-8") as f:
        f.write(zh_summary)

    return {"ru": ru_summary, "zh": zh_summary}
''',

    "scheduler.py": '''
import os
from datetime import datetime
from config import BEIJING_TZ, DATA_DIR
from storage import load_state, save_state, get_cached_report, put_cached_report, ensure_dirs, save_jsonl
from sources import collect_all_candidates
from pipeline.normalize import normalize_and_fetch_details
from pipeline.dedup import dedupe_articles
from pipeline.reports import build_bilingual_summary_for_range


def bj_now():
    return datetime.now(BEIJING_TZ)


def slot_times_for_today():
    now = bj_now()
    d = now.date()

    midday_start = datetime(d.year, d.month, d.day, 7, 0, tzinfo=BEIJING_TZ)
    midday_end = datetime(d.year, d.month, d.day, 12, 0, tzinfo=BEIJING_TZ)

    evening_start = datetime(d.year, d.month, d.day, 12, 0, tzinfo=BEIJING_TZ)
    evening_end = datetime(d.year, d.month, d.day, 20, 0, tzinfo=BEIJING_TZ)

    return {
        "midday": {
            "send_time": "12:00",
            "start": midday_start,
            "end": midday_end,
            "label_ru": "Утренняя сводка по углю",
            "label_zh": "煤炭早间摘要",
        },
        "evening": {
            "send_time": "20:00",
            "start": evening_start,
            "end": evening_end,
            "label_ru": "Вечерняя сводка по углю",
            "label_zh": "煤炭晚间摘要",
        },
    }


def get_current_slot_to_send(now_bj: datetime):
    current_hm = now_bj.strftime("%H:%M")
    for slot_name, slot in slot_times_for_today().items():
        if current_hm == slot["send_time"]:
            return slot_name
    return None


def get_manual_window():
    now = bj_now()
    d = now.date()

    morning_start = datetime(d.year, d.month, d.day, 7, 0, tzinfo=BEIJING_TZ)
    noon = datetime(d.year, d.month, d.day, 12, 0, tzinfo=BEIJING_TZ)
    evening = datetime(d.year, d.month, d.day, 20, 0, tzinfo=BEIJING_TZ)

    if morning_start <= now < noon:
        return {
            "kind": "manual_morning_live",
            "label_ru": "Оперативная сводка по углю",
            "label_zh": "煤炭实时摘要",
            "start": morning_start,
            "end": now,
            "period_name": f"{morning_start.strftime('%H:%M')}–{now.strftime('%H:%M')}",
        }
    elif noon <= now < evening:
        return {
            "kind": "manual_evening_live",
            "label_ru": "Оперативная сводка по углю",
            "label_zh": "煤炭实时摘要",
            "start": noon,
            "end": now,
            "period_name": f"{noon.strftime('%H:%M')}–{now.strftime('%H:%M')}",
        }
    else:
        return {
            "kind": "closed",
            "label_ru": "Оперативная сводка по углю",
            "label_zh": "煤炭实时摘要",
            "start": None,
            "end": None,
            "period_name": None,
        }


def manual_cache_key(window):
    if window["start"] is None or window["end"] is None:
        return "closed"
    rounded_minute = (window["end"].minute // 10) * 10
    rounded_end = window["end"].replace(minute=rounded_minute, second=0, microsecond=0)
    return f"{window['kind']}_{window['start'].strftime('%Y%m%d_%H%M')}_{rounded_end.strftime('%Y%m%d_%H%M')}"


def collect_all_sources_for_range(start_dt, end_dt):
    ensure_dirs()
    stamp = bj_now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(DATA_DIR, stamp)
    os.makedirs(run_dir, exist_ok=True)

    raw_candidates = collect_all_candidates()
    save_jsonl(os.path.join(run_dir, "raw_candidates.jsonl"), raw_candidates)

    normalized, skipped = normalize_and_fetch_details(raw_candidates, start_dt, end_dt)
    save_jsonl(os.path.join(run_dir, "normalized_articles.jsonl"), normalized)
    save_jsonl(os.path.join(run_dir, "skipped_articles.jsonl"), skipped)

    deduped = dedupe_articles(normalized)
    save_jsonl(os.path.join(run_dir, "deduped_articles.jsonl"), deduped)

    return deduped, run_dir


def slot_marker(slot_name: str):
    now = bj_now()
    return f"{now.strftime('%Y-%m-%d')}_{slot_name}"


def get_last_scheduled_report(slot_name: str):
    today = bj_now().strftime("%Y-%m-%d")
    key = f"{today}_{slot_name}"
    cached = get_cached_report(key)
    if not cached:
        return None

    slot = slot_times_for_today()[slot_name]
    return {
        "ru": f"📌 {slot['label_ru']}\\n\\n{cached['report_ru']}",
        "zh": f"📌 {slot['label_zh']}\\n\\n{cached['report_zh']}"
    }


def build_manual_summary():
    window = get_manual_window()
    now = bj_now()

    if window["start"] is None or window["end"] is None:
        return {
            "ru": (
                f"📌 Оперативная сводка по углю\\n"
                f"Время: {now.strftime('%Y-%m-%d %H:%M')} (Пекин)\\n\\n"
                "Сейчас вне рабочего окна для оперативной сводки.\\n"
                "Доступные интервалы:\\n"
                "— с 07:00 до 12:00\\n"
                "— с 12:00 до 20:00"
            ),
            "zh": (
                f"📌 煤炭实时摘要\\n"
                f"时间：{now.strftime('%Y-%m-%d %H:%M')}（北京时间）\\n\\n"
                "当前不在实时摘要生成时段内。\\n"
                "可用时间段：\\n"
                "— 07:00–12:00\\n"
                "— 12:00–20:00"
            )
        }

    cache_key = manual_cache_key(window)
    cached = get_cached_report(cache_key)
    if cached:
        return {
            "ru": (
                f"📌 {window['label_ru']}\\n"
                f"Время: {now.strftime('%Y-%m-%d %H:%M')} (Пекин)\\n"
                f"Период: {window['period_name']} по Пекину\\n\\n"
                f"{cached['report_ru']}"
            ),
            "zh": (
                f"📌 {window['label_zh']}\\n"
                f"时间：{now.strftime('%Y-%m-%d %H:%M')}（北京时间）\\n"
                f"区间：北京时间 {window['period_name']}\\n\\n"
                f"{cached['report_zh']}"
            )
        }

    articles, run_dir = collect_all_sources_for_range(window["start"], window["end"])
    state = load_state()
    previous_summary_ru = state.get("last_summary_ru", "")

    summary_pair = build_bilingual_summary_for_range(
        articles=articles,
        previous_summary_ru=previous_summary_ru,
        start_dt=window["start"],
        end_dt=window["end"],
        run_dir=run_dir,
    )

    put_cached_report(cache_key, summary_pair, {
        "kind": window["kind"],
        "run_dir": run_dir,
        "count_articles": len(articles),
    })

    return {
        "ru": (
            f"📌 {window['label_ru']}\\n"
            f"Время: {now.strftime('%Y-%m-%d %H:%M')} (Пекин)\\n"
            f"Период: {window['period_name']} по Пекину\\n\\n"
            f"{summary_pair['ru']}"
        ),
        "zh": (
            f"📌 {window['label_zh']}\\n"
            f"时间：{now.strftime('%Y-%m-%d %H:%M')}（北京时间）\\n"
            f"区间：北京时间 {window['period_name']}\\n\\n"
            f"{summary_pair['zh']}"
        )
    }


def run_slot(slot_name: str):
    state = load_state()
    marker = slot_marker(slot_name)

    if state["sent_slots"].get(marker):
        return None

    slot = slot_times_for_today()[slot_name]
    cache_key = marker

    cached = get_cached_report(cache_key)
    if cached:
        summary_pair = {"ru": cached["report_ru"], "zh": cached["report_zh"]}
    else:
        articles, run_dir = collect_all_sources_for_range(slot["start"], slot["end"])
        previous_summary_ru = state.get("last_summary_ru", "")
        summary_pair = build_bilingual_summary_for_range(
            articles=articles,
            previous_summary_ru=previous_summary_ru,
            start_dt=slot["start"],
            end_dt=slot["end"],
            run_dir=run_dir,
        )
        put_cached_report(cache_key, summary_pair, {
            "slot_name": slot_name,
            "run_dir": run_dir,
            "count_articles": len(articles),
        })

    state["sent_slots"][marker] = {
        "sent_at": bj_now().strftime("%Y-%m-%d %H:%M"),
        "slot_name": slot_name,
    }
    state["last_summary_ru"] = summary_pair["ru"]
    state["last_summary_zh"] = summary_pair["zh"]
    save_state(state)

    return {
        "ru": f"📌 {slot['label_ru']}\\nВремя выпуска: {bj_now().strftime('%Y-%m-%d %H:%M')} (Пекин)\\n\\n{summary_pair['ru']}",
        "zh": f"📌 {slot['label_zh']}\\n发布时间：{bj_now().strftime('%Y-%m-%d %H:%M')}（北京时间）\\n\\n{summary_pair['zh']}"
    }
''',

    "telegram_ui.py": '''
import asyncio
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from config import TELEGRAM_BOT_TOKEN
from storage import add_subscriber, load_subscribers
from scheduler import build_manual_summary, get_last_scheduled_report


def split_long_text(text: str, chunk_size: int = 3800):
    chunks = []
    current = ""
    for line in text.split("\\n"):
        if len(current) + len(line) + 1 > chunk_size:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def send_telegram_message(chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": str(chat_id), "text": text}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def broadcast_pair(ru_text: str, zh_text: str):
    subs = load_subscribers()
    results = []
    for chat_id in subs["chat_ids"]:
        for chunk in split_long_text(ru_text):
            try:
                results.append(send_telegram_message(chat_id, chunk))
            except Exception:
                pass
        for chunk in split_long_text(zh_text):
            try:
                results.append(send_telegram_message(chat_id, chunk))
            except Exception:
                pass
    return results


def build_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Сформировать сводку сейчас", callback_data="manual_summary")],
        [InlineKeyboardButton("Последняя 12:00", callback_data="last_midday")],
        [InlineKeyboardButton("Последняя 20:00", callback_data="last_evening")],
    ])


async def safe_send_pair(chat_id: str, ru_text: str, zh_text: str, bot):
    for chunk in split_long_text(ru_text):
        await bot.send_message(chat_id=chat_id, text=chunk)
        await asyncio.sleep(0.4)
    for chunk in split_long_text(zh_text):
        await bot.send_message(chat_id=chat_id, text=chunk)
        await asyncio.sleep(0.4)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_subscriber(str(update.effective_chat.id))
    await update.message.reply_text(
        "Бот запущен. Выберите действие:",
        reply_markup=build_main_keyboard()
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    add_subscriber(str(update.effective_chat.id))
    await update.message.reply_text(
        "Меню:",
        reply_markup=build_main_keyboard()
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = str(query.message.chat_id)
    add_subscriber(chat_id)

    await query.answer()

    if query.data == "manual_summary":
        await query.edit_message_text("Формирую сводку. Это может занять несколько минут...")

        try:
            pair = build_manual_summary()
            await safe_send_pair(chat_id, pair["ru"], pair["zh"], context.bot)
        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"Ошибка при формировании сводки: {e}")

    elif query.data == "last_midday":
        pair = get_last_scheduled_report("midday")
        if not pair:
            pair = {
                "ru": "Сегодняшняя сводка на 12:00 пока ещё не сформирована.",
                "zh": "今天12:00的摘要尚未生成。"
            }
        await safe_send_pair(chat_id, pair["ru"], pair["zh"], context.bot)

    elif query.data == "last_evening":
        pair = get_last_scheduled_report("evening")
        if not pair:
            pair = {
                "ru": "Сегодняшняя сводка на 20:00 пока ещё не сформирована.",
                "zh": "今天20:00的摘要尚未生成。"
            }
        await safe_send_pair(chat_id, pair["ru"], pair["zh"], context.bot)


async def build_app():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(button_handler))
    return app
''',

    "main.py": '''
import asyncio
import threading
import time

from storage import ensure_dirs
from telegram_ui import build_app, broadcast_pair
from scheduler import bj_now, get_current_slot_to_send, run_slot


def schedule_loop():
    while True:
        try:
            now = bj_now()
            slot_name = get_current_slot_to_send(now)
            if slot_name:
                pair = run_slot(slot_name)
                if pair:
                    broadcast_pair(pair["ru"], pair["zh"])
        except Exception as e:
            print(f"Scheduler error: {e}")
        time.sleep(30)


async def run_telegram():
    app = await build_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    ensure_dirs()
    t = threading.Thread(target=schedule_loop, daemon=True)
    t.start()
    asyncio.run(run_telegram())
''',

    "sources/__init__.py": '''
from .mysteel_global import collect_links as collect_mysteel_global_links
from .mysteel_fast import collect_links as collect_mysteel_fast_links
from .mysteel_cn_list import collect_links as collect_mysteel_cn_list_links
from .sxcoal import collect_links as collect_sxcoal_links
from .cls import collect_links as collect_cls_links
from utils import fetch_article_details_common


def collect_all_candidates():
    rows = []
    rows.extend(collect_mysteel_global_links())
    rows.extend(collect_mysteel_cn_list_links())
    rows.extend(collect_sxcoal_links())
    rows.extend(collect_cls_links())
    rows.extend(collect_mysteel_fast_links())
    return rows


def fetch_article_details_by_source(item):
    return fetch_article_details_common(item)
''',

    "scheduler.py": None,  # will be filled above already
}

# Fix duplicate key issue by reassigning exact desired contents
FILES["scheduler.py"] = FILES["scheduler.py"]

# Extra files
FILES["pipeline/scoring.py"] = FILES["pipeline/scoring.py"]
FILES["pipeline/facts.py"] = FILES["pipeline/facts.py"]
FILES["pipeline/reports.py"] = FILES["pipeline/reports.py"]
FILES["pipeline/dedup.py"] = FILES["pipeline/dedup.py"]
FILES["pipeline/normalize.py"] = FILES["pipeline/normalize.py"]
FILES["pipeline/clustering.py"] = FILES["pipeline/clustering.py"]
FILES["sources/__init__.py"] = FILES["sources/__init__.py"]

# Add missing empty init files
FILES["sources/__init__.py"] = FILES["sources/__init__.py"]
FILES["pipeline/__init__.py"] = FILES["pipeline/__init__.py"]

ROOT = Path(".")

for path_str, content in FILES.items():
    if content is None:
        continue
    path = ROOT / path_str
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip("\\n"), encoding="utf-8")

print("Project files created.")
print("Next steps:")
print("1) Edit config.py and insert OPENAI_API_KEY + TELEGRAM_BOT_TOKEN")
print("2) Install deps:")
print("   pip3 install --upgrade openai requests beautifulsoup4 python-telegram-bot playwright")
print("   playwright install chromium")
print("3) Check syntax:")
print("   python3 -m py_compile main.py config.py storage.py fx.py telegram_ui.py scheduler.py prompts.py models.py utils.py sources/*.py pipeline/*.py")
print("4) Run manually:")
print("   python3 main.py")
