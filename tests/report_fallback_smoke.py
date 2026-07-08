"""Smoke check that daily/manual LLM failure does not send deterministic fallback text."""

from datetime import datetime
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline.reports as reports


class _FailingResponses:
    def create(self, **kwargs):
        raise RuntimeError("llm unavailable")


class _FailingClient:
    responses = _FailingResponses()


def main():
    old_client = reports.client
    old_analyze = reports.analyze_article
    old_score = reports.score_event
    old_cache_load = reports._load_cache
    old_cache_save = reports._save_cache
    try:
        reports.client = _FailingClient()
        reports.analyze_article = lambda article: {
            "relevant_to_coal": True,
            "new_fact_present": True,
            "event_type": "price_update",
            "segment": "thermal_coal",
            "headline_fact": article.get("title", ""),
            "what_happened": article.get("content", ""),
            "importance_score": 70,
            "repeat_without_new_detail": False,
            "should_enter_top8": True,
        }
        reports.score_event = lambda analysis, article: 70
        reports._load_cache = lambda: {}
        reports._save_cache = lambda cache: None
        with tempfile.TemporaryDirectory() as tmp:
            result = reports.build_bilingual_summary_for_range(
                articles=[{
                    "source": "mysteel",
                    "title": "Mysteel coal price update",
                    "url": "https://example.com/news",
                    "content": "Prices moved in the current report window.",
                    "published_at": "2026-07-08 09:00:00",
                }],
                previous_summary_ru="",
                start_dt=datetime(2026, 7, 7, 20, 0),
                end_dt=datetime(2026, 7, 8, 9, 27),
                run_dir=tmp,
                kind="manual_live",
            )
    finally:
        reports.client = old_client
        reports.analyze_article = old_analyze
        reports.score_event = old_score
        reports._load_cache = old_cache_load
        reports._save_cache = old_cache_save

    assert result["ru"] == "Не удалось подготовить качественную AI-сводку. Попробуйте позже.", result
    assert "найдено" not in result["ru"].lower(), result
    assert "主要来源共有" not in result["zh"], result
    print("report fallback smoke passed")


if __name__ == "__main__":
    main()
