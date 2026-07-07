"""Regression check for LLM-edited daily/manual report prompt and output."""

from datetime import datetime
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline.reports as reports


class _FakeResponse:
    output_text = json.dumps({
        "ru": '⬛ Оперативная сводка по рынку угля КНР\nДата: 7 июля 2026 года\nПериод: 2026-07-07 07:00–2026-07-07 20:00\n\n⬛ Картина дня\nВ фокусе рынка — авария на шахте в Чанчжи и движение цен на коксующийся уголь. Для закупок это важно из-за возможной реакции надзора и краткосрочных остановок добычи.\n\nПортовая и ценовая картина остается рабочей: отдельные сигналы показывают осторожный спрос, но без резкого разворота рынка.\n\n⬛ Новости из источников\n▪️ Mysteel\n1. В районе Чанчжи произошла авария на шахте с гибелью человека; остановлена только затронутая шахта, соседние шахты работают штатно.\nСсылка: https://coal.mysteel.com/a/safety.html\n\n▪️ SXCoal\n1. Цены на коксующийся уголь в Китае немного выросли в течение текущего окна.\nСсылка: https://sxcoal.com/news/price\n\n▪️ CLS\n1. Фьючерсы на коксующийся уголь выросли, что улучшило краткосрочные настроения рынка.\nСсылка: https://cls.cn/detail/1\n\n⬛ Новости по нашим клиентам\nПо клиентам из списка свежих релевантных новостей за период не найдено.',
        "zh": '⬛ 中国煤炭市场动态简报\n日期：2026年7月7日\n期间：2026-07-07 07:00–2026-07-07 20:00\n\n⬛ 今日概况\n市场关注长治煤矿事故及焦煤价格变化。事故可能影响安全监管和短期生产安排。\n\n⬛ 来源新闻\n▪️ Mysteel\n1. 长治区域矿井发生顶板事故致人员遇难，仅涉事矿停产整顿，周边煤矿生产正常。\n链接：https://coal.mysteel.com/a/safety.html\n\n⬛ 客户新闻\n名单内客户在本期未发现新的相关新闻。',
    }, ensure_ascii=False)


class _FakeResponses:
    def __init__(self):
        self.prompt = None

    def create(self, **kwargs):
        self.prompt = kwargs.get("input", "")
        assert "source_groups" in self.prompt, self.prompt
        assert "Mysteel" in self.prompt and "SXCoal" in self.prompt and "CLS" in self.prompt, self.prompt
        assert "safety_high_priority" in self.prompt, self.prompt
        assert "client_news" in self.prompt, self.prompt
        assert "Запрещенные старые заголовки" in self.prompt, self.prompt
        return _FakeResponse()


class _FakeClient:
    def __init__(self):
        self.responses = _FakeResponses()


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
    old_client = reports.client
    fake_client = _FakeClient()
    reports.client = fake_client
    try:
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
        result = reports._build_source_news_report_llm(start_dt, end_dt, analyzed, client_items=[])
    finally:
        reports.client = old_client

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
    assert not re.search(r"найдено \d+ свежих полезных сообщений", ru), ru
    assert "Mysteel煤焦：长治区域矿井发生顶板事故致人员遇难" not in ru, ru
    assert "顶板事故" in result["zh"], result["zh"]
    print("daily report format smoke passed")


if __name__ == "__main__":
    main()
