import re
from datetime import datetime
from typing import Tuple

from bs4 import BeautifulSoup

from pipeline.safety_terms import is_china_safety_event_text
from utils import (
    soup_from_url,
    clean_text,
    normalize_title,
    extract_main_content_from_soup,
    extract_context_block_text,
    is_coal_related,
    parse_dt_from_text,
)

BAD_KEYWORDS = [
    "petcoke", "needle coke", "calcined petcoke",
    "石油焦", "针状焦", "煅烧焦",
    "aluminum", "aluminium", "铝",
    "copper", "铜", "zinc", "锌", "nickel", "镍",
    "iron ore", "铁矿",
    "container", "集装箱",
]

GOOD_KEYWORDS = [
    "coal", "coking coal", "thermal coal", "coke", "pci",
    "煤", "焦煤", "炼焦煤", "动力煤", "焦炭", "喷吹煤", "无烟煤"
]

CURRENT_YEAR = 2026

NO_FETCH_SOURCES = {
    "mysteel_fast",
    "mysteel_jiaotan",
    "mysteel_list_fallback",
    "cls",
}

def _to_naive(dt):
    if not dt:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.replace(tzinfo=None)
    return dt


def _as_dt(x):
    if not x:
        return None
    if isinstance(x, datetime):
        return _to_naive(x)

    s = str(x).strip().replace("Z", "")
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass

    try:
        return _to_naive(datetime.fromisoformat(s))
    except Exception:
        return None


def _looks_bad(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in BAD_KEYWORDS)


def _looks_good(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in GOOD_KEYWORDS)


def _is_important_coal_futures_item(text: str) -> bool:
    """
    CLS commodity-futures headlines often mention many commodities together.
    Do not drop the item only because it also contains aluminum/nickel/lithium/etc.,
    if coke/coking coal has a clear price movement.
    """
    t = text or ""
    low = t.lower()

    coal_terms = ("焦煤", "焦炭", "coking coal", "coke")
    move_terms = (
        "涨超", "跌超", "涨近", "跌近", "上涨", "下跌",
        "开盘", "收跌", "收涨", "主力合约", "商品期货", "国内期货",
        "%", "percent"
    )

    return any(x in low for x in coal_terms) and any(x in low for x in move_terms)


def _infer_dt_from_title_or_url(c):
    title = str(c.get("title", "") or "")
    url = str(c.get("url", "") or "")
    ctx = str(c.get("context_text", "") or "")

    for blob in [title, ctx]:
        dt = parse_dt_from_text(blob)
        if dt:
            return _to_naive(dt)

    m = re.search(r'/a/(\d{2})(\d{2})(\d{2})\d{2}/', url)
    if m:
        yy, mm, dd = m.groups()
        try:
            return datetime(2000 + int(yy), int(mm), int(dd), 12, 0, 0)
        except Exception:
            pass

    m = re.search(r'财联社\s*(\d{1,2})月(\d{1,2})日', title)
    if m:
        mm, dd = m.groups()
        try:
            return datetime(CURRENT_YEAR, int(mm), int(dd), 12, 0, 0)
        except Exception:
            pass

    m = re.search(r'(\d{1,2})月(\d{1,2})日', title)
    if m:
        mm, dd = m.groups()
        try:
            return datetime(CURRENT_YEAR, int(mm), int(dd), 12, 0, 0)
        except Exception:
            pass

    return None


def _extract_dt_from_soup(soup, title="", url=""):
    if not soup:
        return None

    meta_candidates = []
    for key in [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "article:published_time"}),
        ("meta", {"property": "og:published_time"}),
        ("meta", {"name": "pubdate"}),
        ("meta", {"name": "publishdate"}),
        ("meta", {"name": "publish_time"}),
        ("meta", {"name": "date"}),
    ]:
        tag = soup.find(*key)
        if tag:
            meta_candidates.append(tag.get("content") or tag.get("value") or "")

    for s in meta_candidates:
        dt = _as_dt(s)
        if dt:
            return dt

    blobs = []
    try:
        blobs.append(clean_text(soup.get_text(" ", strip=True)))
    except Exception:
        pass

    try:
        blobs.append(clean_text(extract_context_block_text(soup)))
    except Exception:
        pass

    blobs.append(title)
    blobs.append(url)

    for blob in blobs:
        dt = parse_dt_from_text(blob)
        if dt:
            return _to_naive(dt)

    return None


def _candidate_dt(c, soup=None):
    for key in ["list_published_at", "published_at", "published_at_raw"]:
        dt = _as_dt(c.get(key))
        if dt:
            return dt

    dt = _infer_dt_from_title_or_url(c)
    if dt:
        return dt

    dt = _extract_dt_from_soup(soup, c.get("title", ""), c.get("url", ""))
    if dt:
        return dt

    return None


def normalize_and_fetch_details(raw_candidates, start_dt, end_dt) -> Tuple[list, list]:
    normalized = []
    skipped = []

    start_dt = _to_naive(_as_dt(start_dt))
    end_dt = _to_naive(_as_dt(end_dt))

    for c in raw_candidates:
        title = clean_text(c.get("title", ""))
        url = c.get("url", "")
        source = c.get("source", "")
        context = clean_text(c.get("context_text", ""))

        if not title or not url:
            skipped.append({"reason": "empty_title_or_url", "title": title, "url": url, "source": source})
            continue

        if "/stock?code=" in url:
            skipped.append({"reason": "stock_link", "title": title, "url": url, "source": source})
            continue

        blob0 = f"{title} {url} {context}"
        is_china_safety = is_china_safety_event_text(blob0)
        if _looks_bad(blob0) and not _is_important_coal_futures_item(blob0) and not is_china_safety:
            skipped.append({"reason": "bad_keyword", "title": title, "url": url, "source": source})
            continue

        if not _looks_good(blob0) and not is_china_safety:
            skipped.append({"reason": "not_coal_enough", "title": title, "url": url, "source": source})
            continue

        # Быстрый режим: для Mysteel/CLS не ходим в страницу повторно
        if source in NO_FETCH_SOURCES:
            published_at = _to_naive(_candidate_dt(c, soup=None))
            if not published_at:
                skipped.append({"reason": "no_source_datetime", "title": title, "url": url, "source": source})
                continue

            if start_dt and end_dt:
                if published_at.date() == end_dt.date() and published_at > end_dt:
                    published_at = end_dt

                if not (start_dt <= published_at <= end_dt):
                    skipped.append({
                        "reason": "outside_window",
                        "title": title,
                        "url": url,
                        "source": source,
                        "dt": published_at.strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    continue

            content = clean_text(f"{title}. {context}")
            blob = f"{title} {content} {context}"

            if _looks_bad(blob) and not _looks_good(title) and not _is_important_coal_futures_item(blob) and not is_china_safety_event_text(blob):
                skipped.append({"reason": "bad_keyword_after_fetch", "title": title, "url": url, "source": source})
                continue

            if not is_coal_related(blob) and not is_china_safety_event_text(blob):
                skipped.append({"reason": "not_coal_related_after_fetch", "title": title, "url": url, "source": source})
                continue

            normalized.append({
                "source": source,
                "title": title,
                "url": url,
                "content": content,
                "published_at": published_at.strftime("%Y-%m-%d %H:%M:%S"),
                "language": c.get("language", ""),
                "title_norm": normalize_title(title),
                "published_at_raw": c.get("published_at_raw", ""),
            })
            continue

        soup = None
        content = ""

        try:
            soup = soup_from_url(url)
        except Exception:
            soup = None

        published_at = _to_naive(_candidate_dt(c, soup=soup))

        if not published_at:
            skipped.append({"reason": "no_source_datetime", "title": title, "url": url, "source": source})
            continue

        if start_dt and end_dt:
            if published_at.date() == end_dt.date() and published_at > end_dt:
                published_at = end_dt

            if not (start_dt <= published_at <= end_dt):
                skipped.append({
                    "reason": "outside_window",
                    "title": title,
                    "url": url,
                    "source": source,
                    "dt": published_at.strftime("%Y-%m-%d %H:%M:%S"),
                })
                continue

        if soup is not None:
            try:
                content = clean_text(extract_main_content_from_soup(soup))
            except Exception:
                content = ""
            if not content:
                try:
                    content = clean_text(extract_context_block_text(soup))
                except Exception:
                    content = ""

        if not content:
            content = clean_text(f"{title}. {context}")

        blob = f"{title} {content} {context}"

        if _looks_bad(blob) and not _looks_good(title) and not _is_important_coal_futures_item(blob) and not is_china_safety_event_text(blob):
            skipped.append({"reason": "bad_keyword_after_fetch", "title": title, "url": url, "source": source})
            continue

        if not is_coal_related(blob) and not is_china_safety_event_text(blob):
            skipped.append({"reason": "not_coal_related_after_fetch", "title": title, "url": url, "source": source})
            continue

        normalized.append({
            "source": source,
            "title": title,
            "url": url,
            "content": content,
            "published_at": published_at.strftime("%Y-%m-%d %H:%M:%S"),
            "language": c.get("language", ""),
            "title_norm": normalize_title(title),
            "published_at_raw": c.get("published_at_raw", ""),
        })

    return normalized, skipped
