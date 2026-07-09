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
    assert "Baosteel starts up two-strand caster" in ru_section
    assert "baosteel-profile" not in ru_section
    assert "Reuters Pictures" not in ru_section

    ru, zh = append_client_news_sections("⬛ Test RU", "⬛ Test ZH", accepted)
    assert "Иные новости" in ru
    assert "其他新闻" in zh
    print(f"client news smoke passed: {len(accepted)} items")


if __name__ == "__main__":
    main()
