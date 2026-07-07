"""Smoke checks for client-news recency/relevance filtering and formatting."""

from datetime import datetime
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
    rows = [
        {
            "title": "宝钢股份推进焦炭采购长协优化",
            "url": "https://example.com/baosteel-coke",
            "snippet": "今天 宝钢 焦炭 采购 成本 管控",
            "date": "今天",
        },
        {
            "title": "鞍钢高炉检修影响铁水产量",
            "url": "https://example.com/ansteel-output",
            "snippet": "2小时前 鞍钢 高炉 产量 调整",
            "date": "2小时前",
        },
        {
            "title": "华菱钢铁环保限产安排",
            "url": "https://example.com/valin-env",
            "snippet": "2026年7月7日 华菱 环保 停产 检查",
            "date": "2026年7月7日",
        },
        {
            "title": "宝钢公司简介",
            "url": "https://example.com/old-profile",
            "snippet": "公司简介 企业概况",
            "date": "2020年1月1日",
        },
    ]

    items = []
    items += parse_search_result_rows([rows[0], rows[3]], _client("Baosteel"), start, end, now=end)
    items += parse_search_result_rows([rows[1]], _client("Ansteel"), start, end, now=end)
    items += parse_search_result_rows([rows[2]], _client("Valin"), start, end, now=end)

    assert [item["client"] for item in items] == ["Baosteel", "Ansteel", "Valin"], items
    ru_section = format_client_news_ru(items)
    assert "⬛ Новости по нашим клиентам" in ru_section
    assert "Ссылка: https://example.com/baosteel-coke" in ru_section
    assert "old-profile" not in ru_section

    ru, zh = append_client_news_sections("⬛ Test RU", "⬛ Test ZH", items)
    assert "Новости по нашим клиентам" in ru
    assert "客户新闻" in zh
    print(f"client news smoke passed: {len(items)} items")


if __name__ == "__main__":
    main()
