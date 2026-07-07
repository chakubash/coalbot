import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from models import ArticleCandidate
from pipeline.safety_terms import is_china_safety_event_text
from utils import fetch_html, clean_text, md5_text, parse_dt_from_text

URLS = [
    "https://coal.mysteel.com/article/pa4415aaaaaa1.html",
    "https://coal.mysteel.com/",
]

BASE_URL = "https://coal.mysteel.com"

GOOD_HINTS = [
    "煤", "煤炭", "焦煤", "炼焦煤", "焦炭", "动力煤", "无烟煤", "喷吹煤", "配焦煤", "主焦煤"
]

BAD_HINTS = [
    "螺纹钢", "热轧", "冷轧", "铁矿", "废钢", "铜", "铝", "锌", "镍", "不锈钢",
    "光伏", "挖掘机", "工程机械", "钢价", "铁矿石", "烧结机"
]


GENERIC_LINK_TEXT = {"详情", "查看", "更多", "more", "原文", "全文"}


def _clean_candidate_title(text: str) -> str:
    text = clean_text(text)
    text = re.sub(r"^(?:·|•|-|\d{1,2}[:：])\s*", "", text).strip()
    return text


def _anchor_title(a) -> str:
    for attr in ("title", "aria-label"):
        val = _clean_candidate_title(a.get(attr) or "")
        if val and val.lower() not in GENERIC_LINK_TEXT:
            return val
    title = _clean_candidate_title(a.get_text(" ", strip=True))
    if title.lower() in GENERIC_LINK_TEXT:
        return ""
    return title


def _extract_parent_text(a):
    """Return only the nearest list-item sized context, never the whole portal list."""
    title = _anchor_title(a)
    node = a
    fallback = title
    for _ in range(5):
        if not node:
            break
        try:
            txt = clean_text(node.get_text(" ", strip=True))
        except Exception:
            txt = ""
        if txt and title and title in txt and len(txt) <= 600:
            return txt[:600]
        if txt and getattr(node, "name", "") in ("li", "tr") and len(txt) <= 600:
            return clean_text(f"{title} {txt}")[:600]
        if txt and len(txt) <= 200 and len(txt) > len(fallback):
            fallback = clean_text(f"{title} {txt}")
        node = node.parent
    return fallback[:600]


def _coal_enough(text: str) -> bool:
    low = (text or "").lower()
    if is_china_safety_event_text(low):
        return True
    if any(x.lower() in low for x in BAD_HINTS):
        return False
    return any(x.lower() in low for x in GOOD_HINTS)


def collect_links(max_pages: int = 10):
    results = []
    seen = set()

    for url in URLS[:max_pages]:
        try:
            html = fetch_html(url)
            if not html:
                print(f"DEBUG_MYSTEEL_COAL_EMPTY {url}")
                continue

            soup = BeautifulSoup(html, "html.parser")
            page_hits = 0
            page_limit = 40

            for a in soup.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                title = _anchor_title(a)

                if "/a/" not in href or not href.endswith(".html"):
                    continue
                if len(title) < 6:
                    continue

                context_text = _extract_parent_text(a)
                if not _coal_enough(title + " " + context_text):
                    continue

                full_url = urljoin(BASE_URL, href)
                key = md5_text(title + "|" + full_url)
                if key in seen:
                    continue

                list_dt = parse_dt_from_text(context_text) or parse_dt_from_text(title)

                seen.add(key)
                results.append(ArticleCandidate(
                    source="mysteel_coal_portal",
                    title=title,
                    url=full_url,
                    context_text=context_text,
                    list_published_at=list_dt.strftime("%Y-%m-%d %H:%M") if list_dt else None,
                ).__dict__)
                page_hits += 1
                if page_hits >= page_limit:
                    break

            print(f"DEBUG_MYSTEEL_COAL_PAGE {url}: {page_hits}")

        except Exception as e:
            print(f"DEBUG_MYSTEEL_COAL_ERROR {url}: {e}")

    print(f"DEBUG_MYSTEEL_COAL_TOTAL: {len(results)}")
    return results
