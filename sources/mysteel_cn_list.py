from urllib.parse import urljoin
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from models import ArticleCandidate
from config import MYSTEEL_CN_URLS
from utils import fetch_html, clean_text, is_coal_related, md5_text, parse_dt_from_text

BASE_URL = "https://www.mysteel.com"

BAD_HINTS = [
    "螺纹钢", "热轧", "冷轧", "铁矿", "废钢", "铜", "铝", "锌", "镍", "不锈钢",
    "生猪", "玉米", "高粱", "光伏", "工程机械", "挖掘机",
    "建筑钢材", "铁矿石", "钢价", "烧结机"
]

BAD_URL_HINTS = [
    "/zhishi/",
]

NOW = datetime(2026, 4, 8, 23, 59, 59)
FRESH_CUTOFF = NOW - timedelta(days=7)

def _to_naive(dt):
    if not dt:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.replace(tzinfo=None)
    return dt

def _extract_parent_text(a):
    node = a
    best = ""
    for _ in range(5):
        if not node:
            break
        try:
            txt = clean_text(node.get_text(" ", strip=True))
        except Exception:
            txt = ""
        if len(txt) > len(best):
            best = txt
        node = node.parent
    return best[:1500]

def _looks_like_news_href(href: str) -> bool:
    h = (href or "").strip().lower()
    if not h or "javascript:" in h:
        return False
    if any(x in h for x in BAD_URL_HINTS):
        return False
    if "/a/" in h and h.endswith(".html"):
        return True
    if "/article/" in h and h.endswith(".html"):
        return True
    return False

def _is_fresh(dt):
    dt = _to_naive(dt)
    if not dt:
        return False
    return dt >= FRESH_CUTOFF

def collect_links(max_pages: int = 8):
    results = []
    seen = set()

    for url in MYSTEEL_CN_URLS[:max_pages]:
        try:
            html = fetch_html(url)
            if not html:
                print(f"DEBUG_MYSTEEL_PAGE_EMPTY {url}")
                continue

            soup = BeautifulSoup(html, "html.parser")
            page_count = 0

            for a in soup.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                title = clean_text(a.get_text(" ", strip=True))

                if not _looks_like_news_href(href):
                    continue
                if not title or len(title) < 6:
                    continue
                if any(x in title for x in BAD_HINTS):
                    continue
                if not is_coal_related(title):
                    continue

                full_url = urljoin(BASE_URL, href)
                key = md5_text(title + full_url)
                if key in seen:
                    continue

                context_text = _extract_parent_text(a)
                list_dt = _to_naive(parse_dt_from_text(context_text) or parse_dt_from_text(title))

                if not _is_fresh(list_dt):
                    continue

                seen.add(key)
                results.append(ArticleCandidate(
                    source="mysteel_cn_list",
                    title=title,
                    url=full_url,
                    context_text=context_text,
                    list_published_at=list_dt.strftime("%Y-%m-%d %H:%M") if list_dt else None,
                ).__dict__)
                page_count += 1

            print(f"DEBUG_MYSTEEL_PAGE {url}: {page_count}")

        except Exception as e:
            print(f"DEBUG_MYSTEEL_PAGE_ERROR {url}: {e}")

    print(f"DEBUG_MYSTEEL_TOTAL: {len(results)}")
    return results
