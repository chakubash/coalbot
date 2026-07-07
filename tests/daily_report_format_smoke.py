"""Regression check for the simplified daily/manual report format without OpenAI calls."""

from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.reports import _build_source_news_report


def _row(source, title, url, content, published_at, score=70):
    return {
        "article": {
            "source": source,
            "title": title,
            "url": url,
            "content": content,
            "published_at": published_at,
        },
        "analysis": {
            "relevant_to_coal": True,
            "new_fact_present": True,
            "event_type": "safety" if "事故" in title else "price_update",
            "segment": "coking_coal",
            "region": "china",
            "headline_fact": title,
            "what_happened": content,
            "importance_score": score,
            "repeat_without_new_detail": False,
            "should_enter_top8": True,
            "has_numeric_price": "价格" in title,
        },
        "score": score,
    }


def main():
    start_dt = datetime(2026, 7, 7, 7, 0)
    end_dt = datetime(2026, 7, 7, 20, 0)
    analyzed = [
        _row(
            "mysteel_coal_portal",
            "Mysteel煤焦：长治区域矿井发生顶板事故致人员遇难",
            "https://coal.mysteel.com/a/safety.html",
            "涉事矿停产整顿，周边煤矿生产正常",
            "2026-07-07 09:10:00",
            90,
        ),
        _row(
            "sxcoal",
            "SXCoal: China coking coal prices edge higher",
            "https://sxcoal.com/news/price",
            "Prices moved higher in the current window.",
            "2026-07-07 10:00:00",
            65,
        ),
        _row(
            "cls",
            "财联社：焦煤主力合约上涨",
            "https://cls.cn/detail/1",
            "焦煤期货上涨，市场情绪改善",
            "2026-07-07 11:00:00",
            60,
        ),
    ]

    result = _build_source_news_report(
        "⬛ Оперативная сводка",
        "⬛ 实时煤炭摘要",
        start_dt,
        end_dt,
        analyzed,
        client_items=[],
    )

    ru = result["ru"]
    assert "Картина дня" in ru, ru
    assert "Новости из источников" in ru, ru
    assert "Mysteel" in ru and "SXCoal" in ru and "CLS" in ru, ru
    assert "Новости по нашим клиентам" in ru, ru
    assert "Карта рынка" not in ru, ru
    assert "Что отслеживать" not in ru, ru
    assert "Что изменилось с прошлого дня" not in ru, ru
    assert "Ключевые события утра" not in ru, ru
    assert "Картина утра" not in ru, ru
    assert "顶板事故" in result["zh"], result["zh"]
    print("daily report format smoke passed")


if __name__ == "__main__":
    main()
