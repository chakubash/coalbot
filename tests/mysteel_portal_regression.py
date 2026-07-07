"""Regression checks for Mysteel Coal Portal list extraction."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sources.mysteel_coal_portal as portal

FAKE_HTML = """
<html><body>
  <div class="nav">日报 周报 月报 价格行情 会议活动</div>
  <ul class="news-list">
    <li><span>2026-07-07 09:10</span>
      <a href="/a/26070709/SAFETY123.html" title="Mysteel煤焦：长治区域矿井发生顶板事故致人员遇难，仅涉事矿停产整顿，周边煤矿生产正常">详情</a>
    </li>
    <li><span>2026-07-07 10:20</span>
      <a href="/a/26070710/PRICE123.html">Mysteel煤焦：山西焦煤市场价格暂稳运行</a>
    </li>
    <li><span>2026-06-26 18:00</span>
      <a href="/a/26062618/47F5014DE41A6E28.html">2026全国煤焦采购大会山东邹城站圆满结束</a>
    </li>
  </ul>
</body></html>
"""


def main():
    old_urls = portal.URLS
    old_fetch = portal.fetch_html
    try:
        portal.URLS = ["https://coal.mysteel.com/"]
        portal.fetch_html = lambda url: FAKE_HTML
        rows = portal.collect_links(max_pages=1)
    finally:
        portal.URLS = old_urls
        portal.fetch_html = old_fetch

    safety_rows = [r for r in rows if "顶板事故" in r["title"]]
    assert len(safety_rows) == 1, rows
    safety = safety_rows[0]
    assert safety["url"].endswith("/a/26070709/SAFETY123.html"), safety
    assert "全国煤焦采购大会" not in safety["context_text"], safety
    assert "日报 周报 月报" not in safety["context_text"], safety
    assert any("价格暂稳" in r["title"] for r in rows), rows
    print(f"mysteel portal regression passed: {len(rows)} candidates")


if __name__ == "__main__":
    main()
