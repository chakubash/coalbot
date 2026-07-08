"""Regression checks for daily/manual LLM report path and validation."""

from datetime import datetime
import json
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline.reports as reports

GOOD_RU = '''⬛ Оперативная сводка по рынку угля КНР за 8 июля 2026 года

Период: с 20:00 7 июля до 09:27 8 июля по Пекину

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

⬛ Иные новости
Свежих релевантных новостей по отслеживаемым компаниям за период не найдено.'''

GOOD_ZH = '''⬛ 中国煤炭市场动态简报
日期：2026年7月8日
期间：北京时间7月7日20:00至7月8日09:27

⬛ 今日概况
市场关注长治煤矿事故及焦煤价格变化。事故可能影响安全监管和短期生产安排。

⬛ 来源新闻
▪️ Mysteel
1. 长治区域矿井发生顶板事故致人员遇难，仅涉事矿停产整顿，周边煤矿生产正常。
链接：https://coal.mysteel.com/a/safety.html

⬛ 其他新闻
本期未发现跟踪公司相关的新消息。'''

BAD_RU = '''⬛ Оперативная сводка по рынку угля КНР
Период: 2026-07-07 20:00–2026-07-08 09:27

⬛ Картина дня
За период 2026-07-07 20:00–2026-07-08 09:27 найдено 6 свежих полезных сообщений из основных источников.

⬛ Новости из источников
▪️ Mysteel
1. 7月8日陕北动力煤价格以降为主.
Ссылка: javascript:void(0)'''


def _response(ru=GOOD_RU, zh=GOOD_ZH):
    return json.dumps({"ru": ru, "zh": zh}, ensure_ascii=False)


class _FakeResponse:
    def __init__(self, text):
        self.output_text = text


class _FakeResponses:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def create(self, **kwargs):
        prompt = kwargs.get("input", "")
        self.prompts.append(prompt)
        assert "source_groups" in prompt, prompt
        assert "Mysteel" in prompt and "SXCoal" in prompt and "CLS" in prompt, prompt
        assert "client_news" in prompt, prompt
        if not self.outputs:
            raise RuntimeError("no fake output")
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)


class _FakeClient:
    def __init__(self, outputs):
        self.responses = _FakeResponses(outputs)


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


def _run_build(outputs):
    old_client = reports.client
    old_analyze = reports.analyze_article
    old_score = reports.score_event
    old_collect_client_news = reports.collect_client_news
    old_cache_load = reports._load_cache
    old_cache_save = reports._save_cache
    old_marker = reports._log_report_builder_marker
    markers = []
    fake_client = _FakeClient(outputs)
    try:
        reports.client = fake_client
        reports.analyze_article = _analysis_for
        reports.score_event = lambda analysis, article: int(analysis.get("importance_score", 0))
        reports.collect_client_news = lambda *args, **kwargs: []
        reports._load_cache = lambda: {}
        reports._save_cache = lambda cache: None
        reports._log_report_builder_marker = lambda marker: markers.append(marker)
        articles = [
            {"source": "mysteel_coal_portal", "title": "Mysteel煤焦：长治区域矿井发生顶板事故致人员遇难", "url": "https://coal.mysteel.com/a/safety.html", "content": "涉事矿停产整顿，周边煤矿生产正常", "published_at": "2026-07-08 09:10:00"},
            {"source": "sxcoal", "title": "SXCoal: China coking coal prices edge higher", "url": "https://sxcoal.com/news/price", "content": "Prices moved higher in the current window.", "published_at": "2026-07-08 09:00:00"},
            {"source": "cls", "title": "财联社：焦煤主力合约上涨", "url": "https://cls.cn/detail/1", "content": "焦煤期货上涨，市场情绪改善", "published_at": "2026-07-08 08:30:00"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            result = reports.build_bilingual_summary_for_range(
                articles=articles,
                previous_summary_ru="",
                start_dt=datetime(2026, 7, 7, 20, 0),
                end_dt=datetime(2026, 7, 8, 9, 27),
                run_dir=tmp,
                kind="manual_live",
            )
        return result, markers, fake_client.responses.prompts
    finally:
        reports.client = old_client
        reports.analyze_article = old_analyze
        reports.score_event = old_score
        reports.collect_client_news = old_collect_client_news
        reports._load_cache = old_cache_load
        reports._save_cache = old_cache_save
        reports._log_report_builder_marker = old_marker


def _assert_good_ru(ru):
    assert "Картина дня" in ru, ru
    assert "Новости из источников" in ru, ru
    assert "Иные новости" in ru, ru
    assert "Карта рынка" not in ru, ru
    assert "Что отслеживать" not in ru, ru
    assert "Что изменилось с прошлого дня" not in ru, ru
    assert "Ключевые события утра" not in ru, ru
    assert "Картина утра" not in ru, ru
    assert not re.search(r"найдено \d+ свежих полезных сообщений", ru), ru
    assert "Mysteel煤焦：长治区域矿井发生顶板事故致人员遇难" not in ru, ru
    assert "7月8日" not in ru, ru
    assert "javascript:void(0)" not in ru, ru


def main():
    ok, markers, prompts = _run_build([_response()])
    assert markers == ["daily_source_llm"], markers
    assert len(prompts) == 1, prompts
    _assert_good_ru(ok["ru"])
    assert "顶板事故" in ok["zh"], ok["zh"]

    retried, markers, prompts = _run_build([_response(BAD_RU, GOOD_ZH), _response()])
    assert markers == ["daily_source_llm"], markers
    assert len(prompts) == 2, prompts
    assert "ПРЕДЫДУЩИЙ ОТВЕТ НЕ ПРОШЕЛ ВАЛИДАЦИЮ" in prompts[1], prompts[1]
    _assert_good_ru(retried["ru"])

    failed, markers, _ = _run_build([_response(BAD_RU, GOOD_ZH), _response(BAD_RU, GOOD_ZH)])
    assert markers == ["daily_source_llm", "daily_source_fallback"], markers
    assert failed["ru"] == "Не удалось подготовить качественную AI-сводку. Попробуйте позже.", failed
    print("daily report format smoke passed")


if __name__ == "__main__":
    main()
