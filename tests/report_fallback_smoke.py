"""Smoke check for generated reports when strict selection is empty but analyzed rows exist."""

from datetime import datetime
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline.reports as reports


class _FakeResponse:
    output_text = '{"ru":"⬛ Тестовая сводка\\n\\n⬛ Ключевые события\\n▪️ Учтена авария на шахте в Чанчжи.","zh":"⬛ 测试简报\\n\\n⬛ 关键事件\\n▪️ 已纳入长治煤矿事故。"}'


class _FakeResponses:
    def create(self, **kwargs):
        prompt = kwargs.get("input", "")
        assert "长治区域矿井发生顶板事故致人员遇难" in prompt, prompt
        return _FakeResponse()


class _FakeClient:
    responses = _FakeResponses()


def main():
    old_analyze = reports.analyze_article
    old_score = reports.score_event
    old_client = reports.client
    old_collect_client_news = reports.collect_client_news
    old_cache_load = reports._load_cache
    old_cache_save = reports._save_cache

    try:
        reports.analyze_article = lambda article: {
            "relevant_to_coal": True,
            "new_fact_present": True,
            "event_type": "safety",
            "segment": "coking_coal",
            "region": "shanxi",
            "headline_fact": "长治区域矿井发生顶板事故致人员遇难",
            "what_happened": "涉事矿停产整顿，周边煤矿生产正常",
            "importance_score": 80,
            "repeat_without_new_detail": True,
            "should_enter_top8": False,
            "has_numeric_price": False,
        }
        reports.score_event = lambda analysis, article: 90
        reports.client = _FakeClient()
        reports.collect_client_news = lambda *args, **kwargs: []
        reports._load_cache = lambda: {}
        reports._save_cache = lambda cache: None

        with tempfile.TemporaryDirectory() as tmp:
            result = reports.build_bilingual_summary_for_range(
                articles=[{
                    "source": "mysteel_coal_portal",
                    "title": "长治区域矿井发生顶板事故致人员遇难",
                    "url": "https://coal.mysteel.com/a/26070709/SAFETY123.html",
                    "content": "涉事矿停产整顿，周边煤矿生产正常",
                    "published_at": "2026-07-07 09:10:00",
                }],
                previous_summary_ru="",
                start_dt=datetime(2026, 7, 7, 7, 0),
                end_dt=datetime(2026, 7, 7, 20, 0),
                run_dir=tmp,
                kind="20",
            )
    finally:
        reports.analyze_article = old_analyze
        reports.score_event = old_score
        reports.client = old_client
        reports.collect_client_news = old_collect_client_news
        reports._load_cache = old_cache_load
        reports._save_cache = old_cache_save

    assert "значимых новостей по угольному рынку КНР не найдено" not in result["ru"], result["ru"]
    assert "未发现中国煤炭市场的重要消息" not in result["zh"], result["zh"]
    assert "Новости по нашим клиентам" in result["ru"], result["ru"]
    print("report fallback smoke passed: generated summary used analyzed row")


if __name__ == "__main__":
    main()
