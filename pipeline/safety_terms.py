"""Shared detection helpers for China coal industrial-safety events."""

SAFETY_EVENT_TERMS = (
    "事故", "矿难", "坍塌", "塌方", "冒顶", "透水", "瓦斯", "爆炸",
    "遇难", "死亡", "伤者", "受伤", "被困", "救援",
    "非法煤矿", "非法开采", "非法生产", "无证",
    "安全生产", "安全检查", "安全监管", "安监", "督查", "整治",
    "停产整顿", "责令停产", "停产", "限产", "瞒报", "谎报",
    "accident", "mine accident", "mine collapse", "collapse", "gas explosion",
    "illegal mine", "illegal mining", "fatal", "fatality", "fatalities",
    "killed", "dead", "death", "deaths", "safety inspection",
    "safety crackdown", "production halt", "shutdown",
)

CHINA_SAFETY_TERMS = (
    "中国", "国内", "煤矿", "山西", "云南", "会泽", "临汾", "长治",
    "吕梁", "陕西", "内蒙古", "贵州", "河南", "河北", "山东", "新疆",
    "china", "chinese", "shanxi", "shaanxi", "yunnan", "huize",
    "linfen", "changzhi", "lvliang", "lüliang", "inner mongolia",
    "guizhou", "henan", "hebei", "shandong", "xinjiang",
)

FOREIGN_ACCIDENT_TERMS = (
    "india", "indonesia", "australia", "usa", "u.s.", "canada",
    "south africa", "magadan", "brisbane", "индонез", "индия",
    "австрал", "сша", "канада", "юар", "магадан",
)

def _has_any(text: str, terms) -> bool:
    low = (text or "").lower()
    return any(term.lower() in low for term in terms)

def is_safety_event_text(text: str) -> bool:
    return _has_any(text, SAFETY_EVENT_TERMS)

def is_china_safety_event_text(text: str) -> bool:
    low = (text or "").lower()
    return (
        is_safety_event_text(low)
        and _has_any(low, CHINA_SAFETY_TERMS)
        and not _has_any(low, FOREIGN_ACCIDENT_TERMS)
    )
