from utils import md5_text, similarity


def _content_len(row):
    return len((row.get("content") or "").strip())


def dedupe_articles(articles):
    # 1) Сначала жёстко схлопываем по URL: оставляем более полную версию
    by_url = {}
    for art in articles:
        url = (art.get("url") or "").strip()
        if not url:
            continue

        prev = by_url.get(url)
        if not prev:
            by_url[url] = art
            continue

        prev_len = _content_len(prev)
        cur_len = _content_len(art)

        # оставляем ту версию, где контент полнее;
        # при равенстве — с более коротким title (меньше шансов, что это title+teaser каша)
        if cur_len > prev_len:
            by_url[url] = art
        elif cur_len == prev_len:
            if len((art.get("title") or "").strip()) < len((prev.get("title") or "").strip()):
                by_url[url] = art

    url_pass = list(by_url.values())

    # 2) Потом убираем почти одинаковые заголовки в один день
    deduped = []
    for art in url_pass:
        duplicate = False
        for kept in deduped:
            same_day = (art.get("published_at", "")[:10] == kept.get("published_at", "")[:10])
            same_title = similarity(art.get("title", ""), kept.get("title", "")) >= 0.93

            if same_day and same_title:
                kept_len = _content_len(kept)
                art_len = _content_len(art)

                if art_len > kept_len:
                    deduped.remove(kept)
                    deduped.append(art)
                elif art_len == kept_len:
                    if len((art.get("title") or "").strip()) < len((kept.get("title") or "").strip()):
                        deduped.remove(kept)
                        deduped.append(art)

                duplicate = True
                break

        if not duplicate:
            deduped.append(art)

    return deduped
