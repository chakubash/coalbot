
import time
from urllib.parse import urljoin
from models import ArticleCandidate
from config import CLS_COAL_URL
from pipeline.safety_terms import is_china_safety_event_text
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
            if not is_coal_related(title) and not is_china_safety_event_text(title):
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
