import hashlib
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import HEADERS, KEYWORDS, PRICE_KEYWORDS, EXCLUDE, BEIJING_TZ
from auth.session_manager import get_mysteel_html, get_sxcoal_html

CORE_COAL_TERMS = [
    "coal", "coking coal", "thermal coal", "metallurgical coal", "coal import", "coal exports",
    "煤", "煤炭", "焦煤", "炼焦煤", "动力煤", "焦炭", "煤矿", "进口煤", "电煤"
]


def clean_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def md5_text(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def normalize_title(title: str) -> str:
    t = clean_text(title).lower()
    t = re.sub(r"[^\w\u4e00-\u9fff\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def is_coal_related(text: str) -> bool:
    low = (text or "").lower()

    has_any_keyword = any(k.lower() in low for k in KEYWORDS)
    if not has_any_keyword:
        return False

    has_core_coal = any(k.lower() in low for k in CORE_COAL_TERMS)
    if has_core_coal:
        return True

    if any(bad in low for bad in EXCLUDE):
        return False

    return True


def is_price_event_text(text: str) -> bool:
    low = (text or "").lower()
    return any(k.lower() in low for k in PRICE_KEYWORDS)


def fetch_html(url: str) -> Optional[str]:
    try:
        low = (url or "").lower()

        if "mysteel.com" in low:
            html, _ = get_mysteel_html(url)
            return html

        if "sxcoal.com" in low:
            html, _ = get_sxcoal_html(url)
            return html

        resp = requests.get(url, headers=HEADERS, timeout=12)
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
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }

    patterns = [
        ("en_mon", r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s*(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?\b"),
        ("dash",   r"\b(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?\b"),
        ("slash",  r"\b(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?\b"),
        ("dot",    r"\b(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?\b"),
        ("cn_full", r"\b(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\b"),
        ("dash_date", r"\b(\d{4})-(\d{2})-(\d{2})\b"),
        ("slash_date", r"\b(\d{4})/(\d{2})/(\d{2})\b"),
        ("dot_date", r"\b(\d{4})\.(\d{2})\.(\d{2})\b"),
        ("cn_date", r"\b(\d{4})年(\d{1,2})月(\d{1,2})日\b"),
    ]

    for kind, pattern in patterns:
        m = re.search(pattern, text)
        if not m:
            continue

        if kind == "en_mon":
            sec = int(m.group(6) or 0)
            return datetime(
                int(m.group(3)), month_map[m.group(1).lower()], int(m.group(2)),
                int(m.group(4)), int(m.group(5)), sec, tzinfo=BEIJING_TZ
            )

        if kind in ("dash", "slash", "dot", "cn_full"):
            sec = int(m.group(6) or 0)
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)), int(m.group(5)), sec, tzinfo=BEIJING_TZ
            )

        if kind in ("dash_date", "slash_date", "dot_date", "cn_date"):
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                12, 0, 0, tzinfo=BEIJING_TZ
            )

    return None


def extract_context_block_text(soup):
    if not soup:
        return ""

    texts = []
    for tag in soup.find_all(["p", "span", "div"]):
        t = tag.get_text(" ", strip=True)
        if len(t) > 50:
            texts.append(t)

    return " ".join(texts)


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
            text = clean_text(block.get_text("\n", strip=True))
            if len(text) >= 200:
                return text[:7000]

    paragraphs = []
    for p in soup.find_all("p"):
        t = clean_text(p.get_text(" ", strip=True))
        if len(t) >= 40:
            paragraphs.append(t)

    if paragraphs:
        return "\n".join(paragraphs[:30])[:7000]

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
            "language": "zh" if re.search(r"[\u4e00-\u9fff]", fallback_title) else "en",
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

    lang = "zh" if re.search(r"[\u4e00-\u9fff]", f"{title} {content}") else "en"

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


def detect_coal_commodity(text: str):
    t = (text or "").lower()

    if any(x in t for x in ["焦炭", "冶金焦", "一级焦", "准一级焦", "coke"]):
        return "coke"

    if any(x in t for x in ["焦煤", "炼焦煤", "主焦煤", "配焦煤", "1/3焦煤", "瘦焦煤", "肥煤", "coking coal"]):
        return "coking_coal"

    if any(x in t for x in ["动力煤", "电煤", "thermal coal"]):
        return "thermal_coal"

    return "unknown"


def detect_coal_terms_found(text: str):
    t = text or ""
    mapping = {
        "coke": ["焦炭", "冶金焦", "一级焦", "准一级焦", "coke"],
        "coking_coal": ["焦煤", "炼焦煤", "主焦煤", "配焦煤", "1/3焦煤", "瘦焦煤", "肥煤", "coking coal"],
        "thermal_coal": ["动力煤", "电煤", "thermal coal"],
    }

    found = {
        "coke": [],
        "coking_coal": [],
        "thermal_coal": [],
    }

    for bucket, terms in mapping.items():
        for term in terms:
            if term.lower() in t.lower():
                found[bucket].append(term)

    return found


def enforce_segment_consistency(article: dict, analysis: dict):
    text_blob = f"{article.get('title', '')} {article.get('content', '')}"
    hard_segment = detect_coal_commodity(text_blob)
    terms_found = detect_coal_terms_found(text_blob)

    analysis["hard_segment_detected"] = hard_segment
    analysis["hard_terms_found"] = terms_found

    current_segment = analysis.get("segment", "general")

    if hard_segment == "unknown":
        analysis["segment_conflict"] = False
        return analysis

    if hard_segment == "coke" and current_segment == "coking_coal":
        analysis["segment_conflict"] = True
        analysis["segment_before_guard"] = current_segment
        analysis["segment"] = "coke"

    elif hard_segment == "coking_coal" and current_segment == "coke":
        analysis["segment_conflict"] = True
        analysis["segment_before_guard"] = current_segment
        analysis["segment"] = "coking_coal"

    elif hard_segment == "thermal_coal" and current_segment in ["coke", "coking_coal"]:
        analysis["segment_conflict"] = True
        analysis["segment_before_guard"] = current_segment
        analysis["segment"] = "thermal_coal"

    elif current_segment != hard_segment and hard_segment in ["coke", "coking_coal", "thermal_coal"]:
        analysis["segment_conflict"] = True
        analysis["segment_before_guard"] = current_segment
        analysis["segment"] = hard_segment
    else:
        analysis["segment_conflict"] = False

    hf = analysis.get("headline_fact", "")

    if analysis["segment"] == "coke":
        hf = hf.replace("коксующийся уголь", "кокс")
        hf = hf.replace("энергетический уголь", "кокс")

    elif analysis["segment"] == "coking_coal":
        hf = hf.replace("энергетический уголь", "коксующийся уголь")
        hf = hf.replace("кокс", "коксующийся уголь")

    elif analysis["segment"] == "thermal_coal":
        hf = hf.replace("коксующийся уголь", "энергетический уголь")
        hf = hf.replace("кокс", "энергетический уголь")

    analysis["headline_fact"] = hf

    return analysis
