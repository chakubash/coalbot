import os

from zoneinfo import ZoneInfo

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = "7809564417:AAH_xrb1ZzkqEd7_9ml4JZImBuqO6G1QCG4"
PRIMARY_TELEGRAM_CHAT_ID = ""

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

DATA_DIR = "data_runs"
DATA_STATE_DIR = "data"

STATE_FILE = f"{DATA_STATE_DIR}/state.json"
SUBSCRIBERS_FILE = f"{DATA_STATE_DIR}/subscribers.json"
EVENT_MEMORY_FILE = f"{DATA_STATE_DIR}/event_memory.json"
CACHE_FILE = f"{DATA_STATE_DIR}/cache.json"

MYSTEEL_GLOBAL_URL = "https://www.mysteel.net/market-insights/news/latest/"
MYSTEEL_FAST_URL = "https://www.mysteel.com/fastcomment/#/"
MYSTEEL_CN_LIST_TEMPLATE = "https://list1.mysteel.com/article/p-318,355-------------{}.html?keyWord="
SXCOAL_NEWS_URL = "https://www.sxcoal.com/en/news"
CLS_COAL_URL = "https://www.cls.cn/subject/1503"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

KEYWORDS = [
    "coal", "coking coal", "thermal coal", "coke",
    "coal mine", "mine accident", "coal output", "coal price",
    "coal inventory", "coal imports", "coal export",
    "imported coking coal", "seaborne coking coal", "seaborne thermal coal",
    "port", "railway", "rail", "shutdown", "inspection", "safety",
    "production cut", "supply", "steel mill", "blast furnace",
    "power plant", "electricity", "coke plant", "metallurgical coal",
    "freight", "domestic coal", "coal market",
    "煤", "焦煤", "焦炭", "动力煤", "炼焦煤", "煤矿", "港口", "库存",
    "铁路", "运价", "事故", "停产", "安全检查", "进口煤", "出口煤",
    "电厂", "钢厂", "高炉", "焦化", "秦皇岛", "曹妃甸", "黄骅", "日耗", "开工"
]

PRICE_KEYWORDS = [
    "price", "prices", "pricing", "quote", "quoted", "quotation",
    "index", "assessment", "offer", "bid", "premium", "discount",
    "cnf", "fob", "cfr", "spot",
    "港口报价", "报价", "现货价", "价格上涨", "价格下跌",
    "价格上调", "价格下调", "指数", "成交价", "到岸价", "离岸价",
    "进口煤价格", "焦煤价格", "动力煤价格", "焦炭价格"
]

EXCLUDE = [
    "soybean", "lithium", "nickel", "stainless", "battery", "electrolyte",
    "lng", "refined oil", "new energy", "solar", "photovoltaic",
    "polypropylene", "pp", "iron ore", "aluminum", "copper", "zinc",
    "tin", "lead", "manganese", "silicon"
]

MYSTEEL_FAST_URLS = [
    "https://www.mysteel.com/fastcomment/#/?breedTagId=4944",
    "https://www.mysteel.com/fastcomment/#/?breedTagId=4963",
    "https://www.mysteel.com/fastcomment/#/",
]

MYSTEEL_CN_URLS = [
    "https://jiaotan.mysteel.com/article/pa5417aaaaaa1.html",
    "https://jiaotan.mysteel.com/article/pa4300aaaaaa1.html",
    "https://coal.mysteel.com/article/pa4415aaaaaa1.html",
    "https://coal.mysteel.com/",
    "https://list1.mysteel.com/article/p-318-------------1.html",
]
