"""Regression check for the simplified daily/manual report format."""

from datetime import datetime
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline.reports as reports


def _analysis_for(article):
    title = article["title"]
    return {
        "relevant_to_coal": True,
        "new_fact_present": True,
        "event_type": "safety" if "事故" in title else "price_update",
        "segment": "coking_coal",
        "region": "china",
        "headline_fact": title,
        "what_happened": article.get("content", title),
        "importance_score": 80 if "事故" in title else 55,
        "repeat_without_new_detail": False,
        "should_enter_top8": True,
        "has_numeric_price": "价格" in title,
    }


def main():
    old_analyze = reports.analyze_article
    old_score = reports.score_event
    old_collect_client_news = reports.collect_client_news
    old_cache_load = reports._load_cache
    old_cache_save = reports._save_cache
    try:
        reports.analyze_article = _analysis_for
        reports.score_event = lambda analysis, article: int(analysis.get("importance_score", 0))
        reports.collect_client_news = lambda *args, **kwargs: []
        reports._load_cache = lambda: {}
        reports._save_cache = lambda cache: None

        articles = [
            {
                "source": "mysteel_coal_portal",
                "title": "Mysteel煤焦：长治区域矿井发生顶板事故致人员遇难",
                "url": "https://coal.mysteel.com/a/safety.html",
                "content": "涉事矿停产整顿，周边煤矿生产正常",
                "published_at": "2026-07-07 09:10:00",
            },
            {
                "source": "sxcoal",
                "title": "SXCoal: China coking coal prices edge higher",
                "url": "https://sxcoal.com/news/price",
                "content": "Prices moved higher in the current window.",
                "published_at": "2026-07-07 10:00:00",
            },
            {
                "source": "cls",
                "title": "财联社：焦煤主力合约上涨",
                "url": "https://cls.cn/detail/1",
                "content": "焦煤期货上涨，市场情绪改善",
                "published_at": "2026-07-07 11:00:00",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result = reports.build_bilingual_summary_for_range(
                articles=articles,
                previous_summary_ru="",
                start_dt=datetime(2026, 7, 7, 7, 0),
                end_dt=datetime(2026, 7, 7, 20, 0),
                run_dir=tmp,
                kind="manual_live",
            )
    finally:
        reports.analyze_article = old_analyze
        reports.score_event = old_score
        reports.collect_client_news = old_collect_client_news
        reports._load_cache = old_cache_load
        reports._save_cache = old_cache_save

    ru = result["ru"]
    assert "Картина дня" in ru, ru
    assert "Новости из источников" in ru, ru
    assert "Mysteel" in ru and "SXCoal" in ru and "CLS" in ru, ru
    assert "Новости по нашим клиентам" in ru, ru
    assert "Карта рынка" not in ru, ru
    assert "Что отслеживать" not in ru, ru
    assert "Что изменилось с прошлого дня" not in ru, ru
    assert "顶板事故" in result["zh"], result["zh"]
    print("daily report format smoke passed")


if __name__ == "__main__":
    main()
