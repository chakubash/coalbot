"""Smoke checks for collecting China coal safety headlines before report analysis."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.headline_gatekeeper import filter_raw_candidates
from pipeline.safety_terms import is_china_safety_event_text
from sources.mysteel_fast import _coal_enough as mysteel_fast_coal_enough
from sources.mysteel_coal_portal import _coal_enough as mysteel_portal_coal_enough
from sources.mysteel_jiaotan import _coal_enough as mysteel_jiaotan_coal_enough

SAMPLE_HEADLINES = [
    "山西一煤矿发生瓦斯爆炸事故致2人遇难",
    "云南会泽非法煤矿发生坍塌事故，救援正在进行",
    "陕西煤矿安全检查升级，部分矿井被责令停产整顿",
]


def main():
    raw = []
    for i, title in enumerate(SAMPLE_HEADLINES):
        assert is_china_safety_event_text(title), title
        assert mysteel_fast_coal_enough(title), title
        assert mysteel_portal_coal_enough(title), title
        assert mysteel_jiaotan_coal_enough(title), title
        raw.append({
            "source": "cls",
            "title": title,
            "url": f"https://example.com/{i}.html",
            "context_text": "",
        })

    gated = filter_raw_candidates(raw, max_total=10, max_per_source=10)
    assert len(gated) == len(SAMPLE_HEADLINES), gated
    assert all(row.get("_gate_score") == 10000 for row in gated), gated
    print(f"safety collection smoke passed: {len(gated)} headlines")


if __name__ == "__main__":
    main()
