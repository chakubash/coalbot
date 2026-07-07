
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
