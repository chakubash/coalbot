"""Regression check for daily/manual build path using the LLM source editor."""

from datetime import datetime
import json
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline.reports as reports


RU_TEXT = '''⬛ Оперативная сводка по рынку угля КНР
Дата: 7 июля 2026 года
Период: 2026-07-07 07:00–2026-07-07 20:00

⬛ Картина дня
В фокусе рынка — авария на шахте в Чанчжи и движение цен на коксующийся уголь. Для закупок это важно из-за возможной реакции надзора и краткосрочных остановок добычи.

Портовая и ценовая картина остается рабочей: отдельные сигналы показывают осторожный спрос, но без резкого разворота рынка.

⬛ Новости из источников
▪️ Mysteel
1. В районе Чанчжи произошла авария на шахте с гибелью человека; остановлена только затронутая шахта, соседние шахты работают штатно.
Ссылка: https://coal.mysteel.com/a/safety.html

▪️ SXCoal
1. Цены на коксующийся уголь в Китае немного выросли в течение текущего окна.
Ссылка: https://sxcoal.com/news/price

▪️ CLS
1. Фьючерсы на коксующийся уголь выросли, что улучшило краткосрочные настроения рынка.
Ссылка: https://cls.cn/detail/1

⬛ Новости по нашим клиентам
По клиентам из списка свежих релевантных новостей за период не найдено.'''

ZH_TEXT = '''⬛ 中国煤炭市场动态简报
日期：2026年7月7日
期间：2026-07-07 07:00–2026-07-07 20:00

⬛ 今日概况
市场关注长治煤矿事故及焦煤价格变化。事故可能影响安全监管和短期生产安排。

⬛ 来源新闻
▪️ Mysteel
1. 长治区域矿井发生顶板事故致人员遇难，仅涉事矿停产整顿，周边煤矿生产正常。
链接：https://coal.mysteel.com/a/safety.html

⬛ 客户新闻
名单内客户在本期未发现新的相关新闻。'''


class _FakeResponse:
    output_text = json.dumps({"ru": RU_TEXT, "zh": ZH_TEXT}, ensure_ascii=False)


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
        "importance_score": 90 if "事故" in title else 60,
        "repeat_without_new_detail": False,
        "should_enter_top8": True,
        "has_numeric_price": "price" in title.lower() or "价格" in title,
    }


def main():
    old_client = reports.client
    old_analyze = reports.analyze_article
    old_score = reports.score_event
    old_collect_client_news = reports.collect_client_news
    old_cache_load = reports._load_cache
    old_cache_save = reports._save_cache
    old_marker = reports._log_report_builder_marker
    markers = []
    fake_client = _FakeClient()
    try:
        reports.client = fake_client
        reports.analyze_article = _analysis_for
        reports.score_event = lambda analysis, article: int(analysis.get("importance_score", 0))
        reports.collect_client_news = lambda *args, **kwargs: []
        reports._load_cache = lambda: {}
        reports._save_cache = lambda cache: None
        reports._log_report_builder_marker = lambda marker: markers.append(marker)

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
        reports.client = old_client
        reports.analyze_article = old_analyze
        reports.score_event = old_score
        reports.collect_client_news = old_collect_client_news
        reports._load_cache = old_cache_load
        reports._save_cache = old_cache_save
        reports._log_report_builder_marker = old_marker

    assert markers == ["daily_source_llm"], markers
    ru = result["ru"]
    assert "Картина дня" in ru, ru
    assert "Новости из источников" in ru, ru
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
