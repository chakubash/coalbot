"""Smoke checks for client-news debug rows, parser extraction and rejection reasons."""

from datetime import datetime
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sources.client_news as cn

HTML = """
<div id="content_left">
  <div class="result c-container">
    <h3><a href="https://example.com/baosteel">宝钢焦炭采购价格调整</a></h3>
    <span class="c-color-gray">财联社</span>
    <div>今天 宝钢 焦炭 采购 成本 管控</div>
  </div>
</div>
"""


def main():
    rows = cn._parse_baidu_html(HTML, "宝钢 焦炭")
    assert rows and rows[0]["title"] == "宝钢焦炭采购价格调整", rows
    assert rows[0]["url"] == "https://example.com/baosteel", rows

    rss = """<?xml version="1.0"?><rss><channel><item><title>Baosteel starts up two-strand caster in Shanghai</title><link>https://example.com/rss-caster</link><source>Steel News</source><pubDate>Tue, 07 Jul 2026 08:00:00 GMT</pubDate><description>Baosteel commissioned a caster.</description></item></channel></rss>"""
    google_rows = cn._parse_google_news_rss(rss, "Baosteel caster")
    assert google_rows and google_rows[0]["title"].startswith("Baosteel starts"), google_rows

    start = datetime(2026, 7, 7, 7, 0)
    end = datetime(2026, 7, 7, 20, 0)
    client = {"name": "Baosteel", "aliases": ["宝钢"]}
    accepted, reasons = cn.parse_search_result_rows([
        {"title": "宝钢焦炭采购价格调整", "url": "https://example.com/ok", "snippet": "今天 宝钢 焦炭 采购", "date": "今天"},
        {"title": "宝钢公司简介", "url": "https://example.com/profile", "snippet": "公司简介 企业概况", "date": "2020年1月1日"},
        {"title": "其他公司焦炭采购", "url": "https://example.com/other", "snippet": "今天 焦炭 采购", "date": "今天"},
    ], client, start, end, now=end, return_reasons=True)
    assert len(accepted) == 1, accepted
    assert reasons.get("stale_profile_or_report") == 1, reasons
    assert reasons.get("client_alias_not_found") == 1, reasons

    old_google = cn._cached_google_search
    old_baidu = cn._cached_search
    old_load_cache = cn._load_cache
    old_save_cache = cn._save_cache
    old_log_path = cn.BOT_LOG_PATH
    try:
        cn._cached_google_search = lambda query, cache, ttl_seconds, timeout: []
        cn._cached_search = lambda query, cache, ttl_seconds, timeout: []
        cn._load_cache = lambda: {"queries": {}}
        cn._save_cache = lambda cache: None
        with tempfile.TemporaryDirectory() as tmp:
            cn.BOT_LOG_PATH = Path(tmp) / "bot.log"
            debug_rows = []
            items = cn.collect_client_news(start, end, global_timeout=5, per_query_timeout=1, max_queries=1, debug_rows=debug_rows, run_dir=tmp)
            log_text = cn.BOT_LOG_PATH.read_text(encoding="utf-8")
    finally:
        cn._cached_google_search = old_google
        cn._cached_search = old_baidu
        cn._load_cache = old_load_cache
        cn._save_cache = old_save_cache
        cn.BOT_LOG_PATH = old_log_path

    assert items == [], items
    assert debug_rows, debug_rows
    assert all("source_adapter" in row for row in debug_rows), debug_rows
    assert all("resolved_url" in row and "original_google_url" in row for row in debug_rows), debug_rows
    assert all("rejection_reason" in row for row in debug_rows), debug_rows
    assert "CLIENT_NEWS_START" in log_text and "CLIENT_NEWS_DONE" in log_text, log_text
    print("client news debug smoke passed")


if __name__ == "__main__":
    main()
