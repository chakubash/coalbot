"""Smoke checks for client-news recency/relevance filtering and formatting."""

from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources.client_news import (
    CLIENT_WATCHLIST,
    append_client_news_sections,
    format_client_news_ru,
    parse_search_result_rows,
)
import sources.client_news as cn


def _client(name):
    return next(c for c in CLIENT_WATCHLIST if c["name"] == name)


def main():
    start = datetime(2026, 7, 7, 7, 0)
    end = datetime(2026, 7, 7, 20, 0)
    baosteel = _client("Baosteel")
    rows = [
        {
            "title": "Baosteel starts up two-strand caster in Shanghai",
            "url": "https://example.com/baosteel-caster",
            "snippet": "Baosteel and Primetals Technologies commissioned a two-strand caster in Shanghai.",
            "source": "Steel Times",
            "published_dt": end - timedelta(hours=5),
        },
        {
            "title": "Baosteel has ordered two seamless pipe production lines from SMS Group",
            "url": "https://example.com/baosteel-sms-pipe",
            "snippet": "The order covers seamless pipe production lines and equipment for Baosteel.",
            "source": "SMS Group",
            "published_dt": end - timedelta(hours=20),
        },
        {
            "title": "Baosteel Reuters Pictures - steel plant image",
            "url": "https://pictures.reuters.com/archive/baosteel-photo",
            "snippet": "Reuters photo licensing page.",
            "source": "Reuters Pictures",
            "published_dt": end - timedelta(hours=2),
        },
        {
            "title": "Baosteel company profile",
            "url": "https://example.com/baosteel-profile",
            "snippet": "Company profile and corporate overview.",
            "source": "Example",
            "published_dt": end - timedelta(days=20),
        },
    ]

    accepted, reasons = parse_search_result_rows(rows, baosteel, start, end, now=end, return_reasons=True)
    assert [item["title"] for item in accepted] == [
        "Baosteel starts up two-strand caster in Shanghai",
        "Baosteel has ordered two seamless pipe production lines from SMS Group",
    ], accepted
    assert reasons.get("reuters_photo_page") == 1, reasons
    assert reasons.get("stale_profile_or_report") == 1, reasons

    legacy_rows = [
        {"title": "宝钢股份推进焦炭采购长协优化", "url": "https://example.com/baosteel-coke", "snippet": "今天 宝钢 焦炭 采购 成本 管控", "date": "今天"},
        {"title": "鞍钢高炉检修影响铁水产量", "url": "https://example.com/ansteel-output", "snippet": "2小时前 鞍钢 高炉 产量 调整", "date": "2小时前"},
        {"title": "华菱钢铁环保限产安排", "url": "https://example.com/valin-env", "snippet": "2026年7月7日 华菱 环保 停产 检查", "date": "2026年7月7日"},
    ]
    accepted += parse_search_result_rows([legacy_rows[0]], baosteel, start, end, now=end)
    accepted += parse_search_result_rows([legacy_rows[1]], _client("Ansteel"), start, end, now=end)
    accepted += parse_search_result_rows([legacy_rows[2]], _client("Valin"), start, end, now=end)

    ru_section = format_client_news_ru(accepted)
    assert "⬛ Иные новости" in ru_section
    assert "⬛ Иные новости —" not in ru_section
    assert "Baosteel starts up two-strand caster" in ru_section
    assert "baosteel-profile" not in ru_section
    assert "Reuters Pictures" not in ru_section

    ru, zh = append_client_news_sections("⬛ Test RU", "⬛ Test ZH", accepted)
    assert "Иные новости" in ru
    assert "其他新闻" in zh

    long_google = "https://news.google.com/rss/articles/" + "A" * 260
    omitted = format_client_news_ru([{
        "client": "Baosteel",
        "title": "Baosteel starts up two-strand caster in Shanghai",
        "url": long_google,
        "snippet": "Baosteel commissioned a caster.",
    }])
    assert "Baosteel starts up two-strand caster" in omitted
    assert long_google not in omitted
    assert "Ссылка: https://news.google.com/rss/articles/" not in omitted

    google_url = "https://news.google.com/rss/articles/CBMi-test"
    old_resolver = cn._resolve_google_news_url
    old_google = cn._cached_google_search
    old_baidu = cn._cached_search
    old_load = cn._load_cache
    old_save = cn._save_cache
    try:
        cn._resolve_google_news_url = lambda url, timeout=3.0: "https://www.steeltimesint.com/baosteel-caster" if "CBMi-test" in url else url
        accepted_google, google_reasons = parse_search_result_rows([{
            "title": "Baosteel starts up two-strand caster in Shanghai",
            "url": google_url,
            "snippet": "Baosteel commissioned a caster in Shanghai.",
            "published_dt": end,
        }], baosteel, start, end, now=end, return_reasons=True)
        assert accepted_google and accepted_google[0]["url"] == "https://www.steeltimesint.com/baosteel-caster", accepted_google
        assert not google_reasons, google_reasons

        cn._resolve_google_news_url = lambda url, timeout=3.0: url
        unresolved, unresolved_reasons = parse_search_result_rows([{
            "title": "Baosteel starts up two-strand caster in Shanghai",
            "url": google_url,
            "snippet": "Baosteel commissioned a caster in Shanghai.",
            "published_dt": end,
        }], baosteel, start, end, now=end, return_reasons=True)
        assert unresolved == [], unresolved
        assert unresolved_reasons.get("google_url_unresolved") == 1, unresolved_reasons

        stale, stale_reasons = parse_search_result_rows([{
            "title": "Baosteel starts up two-strand caster in Shanghai",
            "url": "https://example.com/stale",
            "snippet": "3 days ago Baosteel commissioned a caster in Shanghai.",
            "date": "3 days ago",
        }], baosteel, start, end, now=end, return_reasons=True)
        assert stale == [], stale
        assert stale_reasons.get("stale_date") == 1, stale_reasons

        weak, weak_reasons = parse_search_result_rows([{
            "title": "Baosteel green update has no direct immediate effect on coking coal demand",
            "url": "https://example.com/weak",
            "snippet": "Baosteel steel ESG update says no direct immediate effect on coking coal demand.",
            "published_dt": end,
        }], baosteel, start, end, now=end, return_reasons=True)
        assert weak == [], weak
        assert weak_reasons.get("weak_business_relevance") == 1, weak_reasons

        def fake_google(query, cache, ttl_seconds, timeout):
            if query == "Baosteel":
                return [
                    {"title": f"Baosteel starts up caster project {i}", "url": f"https://example.com/baosteel-{i}", "snippet": "Baosteel steel caster production line commissioned.", "published_dt": end}
                    for i in range(5)
                ]
            if query == "Ansteel":
                return [{"title": "Ansteel blast furnace maintenance affects output", "url": "https://example.com/ansteel", "snippet": "Ansteel steel blast furnace maintenance.", "published_dt": end}]
            if query == "Valin":
                return [{"title": "Valin rolling mill starts production", "url": "https://example.com/valin", "snippet": "Valin steel rolling mill production starts.", "published_dt": end}]
            if query == "Yongfeng":
                return [{"title": "Yongfeng coke oven maintenance plan", "url": "https://example.com/yongfeng", "snippet": "Yongfeng coke oven maintenance affects production.", "published_dt": end}]
            if query == "Risun":
                return [{"title": "Risun coke procurement contract signed", "url": "https://example.com/risun", "snippet": "Risun coke procurement contract.", "published_dt": end}]
            if query == "Ben Steel":
                return [{"title": "Ben Steel sinter plant resumes", "url": "https://example.com/bensteel", "snippet": "Ben Steel sinter plant production resumes.", "published_dt": end}]
            return []

        cn._cached_google_search = fake_google
        cn._cached_search = lambda query, cache, ttl_seconds, timeout: []
        cn._load_cache = lambda: {"queries": {}}
        cn._save_cache = lambda cache: None
        debug_rows = []
        collected = cn.collect_client_news(start, end, global_timeout=5, per_query_timeout=1, max_queries=20, debug_rows=debug_rows)
        assert len(collected) == 5, collected
        assert len({item["client"] for item in collected}) == 5, collected
        assert sum(1 for item in collected if item["client"] == "Baosteel") == 1, collected
        assert all("news.google.com/rss/articles" not in item.get("url", "") for item in collected), collected
        assert any(row.get("rejection_reason") == "duplicate_client" for row in debug_rows), debug_rows
    finally:
        cn._resolve_google_news_url = old_resolver
        cn._cached_google_search = old_google
        cn._cached_search = old_baidu
        cn._load_cache = old_load
        cn._save_cache = old_save
    print(f"client news smoke passed: {len(accepted)} items")


if __name__ == "__main__":
    main()
