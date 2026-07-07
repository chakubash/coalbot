
ACCIDENT_PRIORITY_TERMS = [
    "事故", "矿难", "坍塌", "塌方", "冒顶", "透水", "瓦斯", "爆炸",
    "遇难", "死亡", "受伤", "被困", "救援",
    "非法煤矿", "非法开采", "安全生产", "安全检查", "安全监管",
    "停产整顿", "责令停产", "瞒报", "谎报",
    "accident", "mine accident", "collapse", "gas explosion",
    "illegal mine", "illegal mining", "fatal", "killed", "dead",
    "safety inspection", "safety crackdown"
]

def accident_priority_boost(text: str) -> int:
    low = (text or "").lower()
    if any(t.lower() in low for t in ACCIDENT_PRIORITY_TERMS):
        return 10000
    return 0

from datetime import datetime, timedelta
from config import BEIJING_TZ
from storage import load_event_memory, save_event_memory
from utils import md5_text, is_price_event_text


def event_fingerprint(analysis: dict):
    base = (
        str(analysis.get("event_type", "")) + "|" +
        str(analysis.get("segment", "")) + "|" +
        str(analysis.get("region", "")) + "|" +
        str(analysis.get("headline_fact", ""))
    )
    return md5_text(base.lower())


def is_old_repeat(analysis: dict, days: int = 5):
    memory = load_event_memory()
    now = datetime.now(BEIJING_TZ)
    fp = event_fingerprint(analysis)

    for item in memory.get("events", []):
        if item.get("fingerprint") != fp:
            continue
        try:
            dt = datetime.strptime(item["seen_at"], "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING_TZ)
        except Exception:
            continue
        if now - dt <= timedelta(days=days):
            return True
    return False


def remember_events(analyzed_events: list):
    memory = load_event_memory()
    now_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")

    for ev in analyzed_events:
        memory["events"].append({
            "fingerprint": event_fingerprint(ev["analysis"]),
            "seen_at": now_str,
            "headline_fact": ev["analysis"].get("headline_fact", "")
        })

    memory["events"] = memory["events"][-500:]
    save_event_memory(memory)


def score_event(analysis: dict, article: dict = None):
    # Score is for a Russian coal exporter selling into China.
    # This is NOT a generic global coal news score.
    score = int(analysis.get("importance_score", 0) or 0)

    event_type = str(analysis.get("event_type", "") or "").lower()
    segment = str(analysis.get("segment", "") or "").lower()
    region = str(analysis.get("region", "") or "").lower()
    exporter_relevance = str(analysis.get("exporter_relevance", "low") or "low").lower()
    repeat_without_new_detail = bool(analysis.get("repeat_without_new_detail", False))
    has_price = bool(analysis.get("has_numeric_price"))
    new_fact_present = bool(analysis.get("new_fact_present", False))

    title = ""
    content = ""
    source = ""
    url = ""
    if article:
        title = str(article.get("title", "") or "")
        content = str(article.get("content", "") or "")
        source = str(article.get("source", "") or "")
        url = str(article.get("url", "") or "")

    combined_text = " ".join([
        title, content, source, url,
        str(analysis.get("headline_fact", "") or ""),
        str(analysis.get("what_happened", "") or ""),
        str(analysis.get("exporter_note", "") or ""),
        region,
        segment,
        event_type,
    ]).lower()

    # ===== Core relevance to China import market =====
    china_core_terms = [
        "china", "chinese", "中国", "国内", "华北", "华东", "华南", "沿海",
        "tangshan", "唐山", "shanxi", "山西", "shaanxi", "陕西",
        "ordos", "鄂尔多斯", "yulin", "榆林",
        "qinhuangdao", "秦皇岛", "caofeidian", "曹妃甸", "huanghua", "黄骅",
        "ganqimaodu", "甘其毛都", "ceke", "策克", "策克口岸",
        "steel mill", "钢厂", "power plant", "电厂", "coke plant", "焦企",
        "port stock", "港口库存", "库存", "到港", "发运", "进口煤", "进口焦煤", "进口动力煤",
        "cfr china", "south china", "north china", "delivered to china"
    ]

    china_supplier_terms = [
        "mongol", "mongolia", "蒙古", "ganqimaodu", "甘其毛都", "ceke", "策克",
        "indonesia", "indonesian", "印尼",
        "russia", "russian", "俄罗斯",
        "australia", "australian", "澳大利亚"
    ]

    direct_trade_terms = [
        "cfr china", "delivered to china", "china import", "imports into china",
        "shipments to china", "exports to china", "进口", "到港", "中国进口",
        "沿海电厂", "华南港口", "北方港口"
    ]

    weak_global_terms = [
        "coal india", "india", "brisbane", "canada", "u.s.", "usa", "united states",
        "magadan", "магадан", "colombia", "south africa", "poland", "vietnam"
    ]

    accident_terms = [
        "accident", "fatal", "killed", "collapse", "обруш", "погиб", "авар"
    ]

    has_china_core = any(t in combined_text for t in china_core_terms)
    has_china_supplier = any(t in combined_text for t in china_supplier_terms)
    has_direct_trade = any(t in combined_text for t in direct_trade_terms)
    weak_global = any(t in combined_text for t in weak_global_terms)
    accident_without_china_trade = any(t in combined_text for t in accident_terms) and not (has_china_core or has_direct_trade)

    # ===== Hard demotion/exclusion logic =====
    # Accidents outside China/import-to-China chain should not enter top unless direct supply/logistics impact is stated.
    if accident_without_china_trade:
        score = min(score, 8)

    # Generic global production/statistics without China link are background only.
    if weak_global and not (has_china_core or has_direct_trade):
        score = min(score, 22)

    # Teasers/repeats remain weak.
    if repeat_without_new_detail:
        score -= 35

    if analysis.get("should_enter_top8") is False:
        score -= 25

    if not analysis.get("relevant_to_coal", True):
        return 0

    # ===== Positive scoring =====
    if new_fact_present:
        score += 8

    # China/internal China/direct import to China is the main target.
    if has_china_core:
        score += 35

    if has_direct_trade:
        score += 35

    # Critical China-core events must not be lost:
    # mine accidents, safety inspections, shutdowns and policy shifts inside China
    # directly affect domestic supply, imports, port flows and buyer behavior.
    if has_china_core and event_type in ["accident", "shutdown", "safety", "policy"]:
        score += 35

    # Suppliers matter only when connected to seaborne/import/CFR/China context.
    if has_china_supplier and any(x in combined_text for x in ["import", "export", "shipment", "cfr", "fob", "port", "cargo", "进口", "出口", "发运", "到港"]):
        score += 18

    # Event type bonuses, but China-centered events get the real priority.
    if event_type in ["price", "price_update"]:
        score += 14
    if has_price:
        score += 10
    if is_price_event_text(combined_text):
        score += 6
    if event_type in ["port", "rail", "logistics", "import", "export", "inventory"]:
        score += 12
    if event_type in ["demand", "supply", "policy"]:
        score += 8
    if event_type in ["accident", "shutdown", "safety"]:
        # Only important if it touches China or direct supply to China.
        score += 12 if (has_china_core or has_direct_trade) else 0

    if exporter_relevance == "high":
        score += 8
    elif exporter_relevance == "medium":
        score += 4

    # Specific China market locations/indicators.
    for t in [
        "tangshan", "唐山", "ordos", "鄂尔多斯", "yulin", "榆林",
        "qinhuangdao", "秦皇岛", "caofeidian", "曹妃甸", "huanghua", "黄骅",
        "ganqimaodu", "甘其毛都", "ceke", "策克",
        "портовые запасы", "港口库存", "north china ports", "bohai", "环渤海"
    ]:
        if t in combined_text:
            score += 12

    # Weak formats and low-value index pages.
    weak_formats = [
        "daily track", "daily index", "market in figures", "purchase price",
        "weekly:", "review:", "cci chinese"
    ]
    if any(x in combined_text for x in weak_formats):
        score -= 12

    # Auctions are not trash if China/Mongolia coking coal is involved.
    if any(x in combined_text for x in ["auction", "e-auction", "竞拍", "线上竞拍"]):
        if has_china_core or "mongol" in combined_text or "蒙古" in combined_text:
            score += 4
        else:
            score -= 10

    if is_old_repeat(analysis):
        score -= 18

    return max(0, min(score, 100))

