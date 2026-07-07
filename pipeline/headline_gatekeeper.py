
# High-priority China coal safety / accident terms.
# These must pass headline gating even without price words.
ACCIDENT_FORCE_KEEP_TERMS = [
    "事故", "矿难", "坍塌", "塌方", "冒顶", "透水", "瓦斯", "爆炸",
    "遇难", "死亡", "受伤", "被困", "救援",
    "非法煤矿", "非法开采", "安全生产", "安全检查", "安全监管",
    "停产整顿", "责令停产", "瞒报", "谎报",
    "accident", "mine accident", "collapse", "gas explosion",
    "illegal mine", "illegal mining", "fatal", "killed", "dead",
    "safety inspection", "safety crackdown"
]

from collections import defaultdict

BLOCK_KEYWORDS = [
    "petcoke", "petroleum coke", "needle coke", "calcined petcoke",
    "石油焦", "针状焦", "煅烧焦",
    "aluminum", "aluminium", "铝",
    "building materials", "rebar", "建筑钢材", "螺纹钢", "高线", "盘螺",
]

POSITIVE_KEYWORDS = [
    "coal", "coke", "coking", "thermal", "anthracite", "pci",
    "煤", "焦煤", "炼焦煤", "动力煤", "焦炭",
    "price", "prices", "index", "cci", "报价", "价格", "指数",
    "import", "export", "进口", "出口",
    "port", "ports", "港", "港口",
    "inventory", "stock", "库存",
    "mine", "mining", "煤矿", "安全", "accident", "shutdown", "停产",
    "rail", "shipping", "freight", "物流", "运输",
    "steel", "mill", "钢厂", "钢铁",
    "bid", "tender", "deal", "成交",
]

WEAK_BUT_KEEP = [
    "sector", "shares", "stock", "板块", "股价",
    "policy", "tariff", "关税", "政策",
]

def _norm(s: str) -> str:
    return " ".join(str(s).lower().split())

def _title(c):
    return _norm(c.get("title", ""))

def _url(c):
    return _norm(c.get("url", ""))

def _context(c):
    return _norm(c.get("context_text", ""))

def _score_candidate(c):
    title = _title(c)
    url = _url(c)
    ctx = _context(c)

    score = 0

    # Сначала смотрим заголовок — это главное
    for kw in POSITIVE_KEYWORDS:
        if kw in title:
            score += 3

    # URL — вторично
    for kw in POSITIVE_KEYWORDS:
        if kw in url:
            score += 2

    # context_text используем очень мягко, чтобы не словить мусор из навигации
    for kw in POSITIVE_KEYWORDS:
        if kw in ctx:
            score += 1

    for kw in WEAK_BUT_KEEP:
        if kw in title:
            score += 1
        elif kw in url:
            score += 1

    # Явный мусор режем
    blob = f"{title} {url}"
    for kw in BLOCK_KEYWORDS:
        if kw in blob:
            return -999

    # Subject/专题 страницы режем
    if "/subject/" in url or "/zt/" in url:
        return -999

    return score

def filter_raw_candidates(raw_candidates, max_total=220, max_per_source=80):
    scored = []
    seen = set()
    by_source = defaultdict(int)

    for c in raw_candidates:
        if c.get("source") == "mysteel_global":
            continue
        title = _title(c)
        url = _url(c)

        key = (title, url)
        if key in seen:
            continue
        seen.add(key)

        score = _score_candidate(c)
        if score < 1:
            continue

        cc = dict(c)
        cc["_gate_score"] = score
        scored.append(cc)

    scored.sort(key=lambda x: x.get("_gate_score", 0), reverse=True)

    out = []
    for c in scored:
        source = c.get("source", "unknown")
        if by_source[source] >= max_per_source:
            continue
        by_source[source] += 1
        out.append(c)
        if len(out) >= max_total:
            break

    return out
