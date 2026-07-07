import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from models import ArticleCandidate
from config import MYSTEEL_FAST_URLS
from utils import clean_text, md5_text, parse_dt_from_text

BASE_URL = "https://www.mysteel.com"

GOOD_HINTS = [
    "煤", "煤炭", "焦煤", "炼焦煤", "焦炭", "动力煤", "无烟煤", "喷吹煤", "配焦煤", "主焦煤", "瘦煤", "肥煤",
    "coking coal", "thermal coal", "coal", "coke", "pci"
]

BAD_HINTS = [
    "螺纹钢", "热轧", "冷轧", "铁矿", "废钢", "铜", "铝", "锌", "镍", "不锈钢",
    "生猪", "玉米", "高粱", "光伏", "工程机械", "挖掘机",
    "钢铁公司", "炼钢工艺", "钢价", "铁矿石"
]


def _coal_enough(text: str) -> bool:
    low = (text or "").lower()
    if any(x.lower() in low for x in BAD_HINTS):
        return False
    return any(x.lower() in low for x in GOOD_HINTS)


def _extract_block(node):
    best = ""
    cur = node
    for _ in range(6):
        if not cur:
            break
        try:
            txt = clean_text(cur.get_text(" ", strip=True))
        except Exception:
            txt = ""
        if len(txt) > len(best):
            best = txt
        cur = cur.parent
    return best[:2000]


def _clean_title(txt: str) -> str:
    txt = clean_text(txt)
    txt = re.sub(r"^详情\s*：\s*", "", txt)
    txt = txt.replace("分享到 QQ空间 新浪微博 微信", " ")
    txt = re.sub(r"\s+", " ", txt).strip()
    if " 详情 ： " in txt:
        txt = txt.split(" 详情 ： ", 1)[-1].strip()
    return txt


def _looks_newsish(text: str) -> bool:
    text = clean_text(text)
    if len(text) < 12:
        return False
    if not _coal_enough(text):
        return False
    return True


def collect_links(max_items: int = 120):
    results = []
    seen = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")

            for url in MYSTEEL_FAST_URLS:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=120000)
                time.sleep(3)

                for _ in range(8):
                    page.mouse.wheel(0, 3200)
                    time.sleep(0.8)

                html = page.content()
                soup = BeautifulSoup(html, "html.parser")

                page_hits = 0

                for node in soup.find_all(["div", "li", "a"]):
                    raw_text = clean_text(node.get_text(" ", strip=True))
                    if not _looks_newsish(raw_text):
                        continue

                    context_text = _extract_block(node)
                    if not _coal_enough(context_text):
                        continue

                    title = _clean_title(raw_text)
                    if not title:
                        continue

                    href = ""
                    if getattr(node, "name", "") == "a" and node.get("href"):
                        href = (node.get("href") or "").strip()
                    else:
                        link = node.find("a", href=True)
                        if link:
                            href = (link.get("href") or "").strip()

                    full_url = urljoin(BASE_URL, href) if href else url
                    key = md5_text(title + "|" + full_url)
                    if key in seen:
                        continue
                    seen.add(key)

                    list_dt = parse_dt_from_text(context_text) or parse_dt_from_text(title)

                    results.append(ArticleCandidate(
                        source="mysteel_fast",
                        title=title,
                        url=full_url,
                        context_text=context_text,
                        list_published_at=list_dt.strftime("%Y-%m-%d %H:%M") if list_dt else None,
                    ).__dict__)
                    page_hits += 1

                    if len(results) >= max_items:
                        break

                print(f"DEBUG_MYSTEEL_FAST_URL {url}: {page_hits}")
                page.close()

                if len(results) >= max_items:
                    break

            browser.close()

    except Exception as e:
        print(f"DEBUG_MYSTEEL_FAST_ERROR: {e}")
        return []

    print(f"DEBUG_MYSTEEL_FAST_TOTAL: {len(results)}")
    return results
