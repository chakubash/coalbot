import time
import requests
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from models import ArticleCandidate
from config import SXCOAL_NEWS_URL
from utils import clean_text, is_coal_related, md5_text, parse_dt_from_text, fetch_html

def fetch_html_fallback(url: str) -> str:
    """
    SXCoal иногда не отдаёт HTML через browser/CDP fetch_html.
    Тогда пробуем обычный HTTP-запрос с нормальными headers.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://www.sxcoal.com/en",
        }
        r = requests.get(url, headers=headers, timeout=7)
        if r.status_code != 200:
            print(f"DEBUG_SXCOAL_REQUESTS_STATUS {url}: {r.status_code}")
            return ""
        return r.text or ""
    except Exception as e:
        print(f"DEBUG_SXCOAL_REQUESTS_ERROR {url}: {e}")
        return ""


def _extract_candidates_from_html(html: str):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue

        if "/en/news/detail/" not in href and "/news/detail/" not in href:
            continue

        title = clean_text(a.get_text(" ", strip=True))
        if not title or len(title) < 10:
            continue
        if not is_coal_related(title):
            continue

        full_url = urljoin("https://www.sxcoal.com", href)
        key = md5_text(title + full_url)
        if key in seen:
            continue
        seen.add(key)

        parent = a.parent
        parent_text = clean_text(parent.get_text(" ", strip=True)) if parent else ""
        list_dt = parse_dt_from_text(parent_text)

        rows.append(ArticleCandidate(
            source="sxcoal",
            title=title,
            url=full_url,
            context_text=parent_text,
            list_published_at=list_dt.strftime("%Y-%m-%d %H:%M") if list_dt else None,
        ).__dict__)

    return rows


def collect_links(max_pages: int = 2):
    results = []
    seen = set()

    urls = [SXCOAL_NEWS_URL]
    for p in range(2, max_pages + 1):
        urls.append(f"{SXCOAL_NEWS_URL}?page={p}")

    for url in urls:
        try:
            html = fetch_html(url)
        except Exception as e:
            print(f"DEBUG_SXCOAL_BROWSER_ERROR {url}: {e}")
            html = ""

        if not html:
            print(f"DEBUG_SXCOAL_BROWSER_EMPTY {url}; trying requests fallback")
            html = fetch_html_fallback(url)

        if not html:
            print(f"DEBUG_SXCOAL_EMPTY {url}")
            continue

        page_rows = _extract_candidates_from_html(html)
        print(f"DEBUG_SXCOAL_PAGE {url}: {len(page_rows)}")

        if not page_rows and url != SXCOAL_NEWS_URL:
            break

        for row in page_rows:
            key = md5_text(row["title"] + row["url"])
            if key in seen:
                continue
            seen.add(key)
            results.append(row)

        time.sleep(1)

    print(f"DEBUG_SXCOAL_TOTAL: {len(results)}")
    return results
