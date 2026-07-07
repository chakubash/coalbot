import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

CLIENT_NEWS_BEIJING_TZ = ZoneInfo("Asia/Shanghai") if ZoneInfo else timezone(timedelta(hours=8))


def _to_client_news_dt(value):
    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        try:
            dt = datetime.fromisoformat(text)
        except Exception:
            dt = None
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M",
                "%Y-%m-%d",
                "%Y/%m/%d",
            ):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except Exception:
                    pass
            if dt is None:
                return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=CLIENT_NEWS_BEIJING_TZ)
    return dt.astimezone(CLIENT_NEWS_BEIJING_TZ)

from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote_plus, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from config import DATA_STATE_DIR, HEADERS
from utils import clean_text, md5_text

CLIENT_WATCHLIST = [
    {"name": "Baosteel", "aliases": ["宝钢", "宝山钢铁"]},
    {"name": "Ansteel", "aliases": ["鞍钢"]},
    {"name": "Risun", "aliases": ["旭阳"]},
    {"name": "Shengmeng-Xiangyu", "aliases": []},
    {"name": "Yuanli", "aliases": []},
    {"name": "Ganglu-AVIC", "aliases": []},
    {"name": "Yongfeng", "aliases": ["永锋"]},
    {"name": "Ben Steel", "aliases": ["本钢"]},
    {"name": "Lingyuan Steel", "aliases": ["凌源钢铁", "凌钢"]},
    {"name": "HK Fertile", "aliases": []},
    {"name": "Ningbo Fuchen", "aliases": []},
    {"name": "Zenit-AVIC", "aliases": []},
    {"name": "Mingkai", "aliases": []},
    {"name": "Haiming", "aliases": []},
    {"name": "Shuangying", "aliases": []},
    {"name": "ZJMI", "aliases": []},
    {"name": "Chengtong-Chongsteel", "aliases": []},
    {"name": "Sanming Steel", "aliases": ["三明钢铁"]},
    {"name": "Sinogiant", "aliases": []},
    {"name": "SUMEC-Esteel", "aliases": ["苏美达", "SUMEC"]},
    {"name": "Liu Steel", "aliases": ["柳钢"]},
    {"name": "Yaxin", "aliases": ["亚新"]},
    {"name": "Lubao", "aliases": ["鲁宝"]},
    {"name": "Valin", "aliases": ["华菱"]},
    {"name": "Zhuokang", "aliases": []},
]

QUERY_TERMS = ("煤炭", "焦煤", "焦炭", "钢铁", "采购", "港口", "事故", "停产", "环保", "亏损", "利润", "产量")
RELEVANCE_TERMS = QUERY_TERMS + (
    "煤", "焦", "高炉", "铁水", "炼钢", "供应", "合同", "招标", "运输", "物流", "安全", "检查", "减产", "复产"
)
STALE_TERMS = ("公司简介", "企业简介", "公司概况", "百科", "招聘", "周报", "月报", "年度报告", "年报")
CACHE_PATH = Path(DATA_STATE_DIR) / "client_news_cache.json"


@dataclass
class ClientNewsItem:
    client: str
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    published_at: str = ""
    query: str = ""

    def as_dict(self) -> dict:
        return {
            "client": self.client,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "published_at": self.published_at,
            "query": self.query,
        }


def _load_cache() -> dict:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"queries": {}}


def _save_cache(cache: dict):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _client_search_aliases(client: dict) -> list[str]:
    aliases = list(client.get("aliases") or [])
    if aliases:
        return aliases[:2]
    return [client["name"]]


def iter_client_queries(max_queries: int = 35) -> Iterable[tuple[dict, str]]:
    made = 0
    for client in CLIENT_WATCHLIST:
        aliases = _client_search_aliases(client)
        terms = ("煤炭", "钢铁", "采购") if client.get("aliases") else ("钢铁",)
        for alias in aliases:
            for term in terms:
                if made >= max_queries:
                    return
                made += 1
                yield client, f"{alias} {term}"


def _parse_baidu_time(text: str, now: datetime) -> Optional[datetime]:
    text = clean_text(text)
    if not text:
        return None
    if "小时前" in text:
        m = re.search(r"(\d+)\s*小时前", text)
        if m:
            return now - timedelta(hours=int(m.group(1)))
    if "分钟前" in text:
        m = re.search(r"(\d+)\s*分钟前", text)
        if m:
            return now - timedelta(minutes=int(m.group(1)))
    if "今天" in text:
        return now.replace(hour=12, minute=0, second=0, microsecond=0)
    if "昨天" in text or "昨日" in text:
        return (now - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    m = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return datetime(y, mo, d, 12, 0, 0)
        except Exception:
            return None
    m = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if m:
        mo, d = map(int, m.groups())
        try:
            return datetime(now.year, mo, d, 12, 0, 0)
        except Exception:
            return None
    return None


def _unwrap_baidu_url(url: str) -> str:
    if "baidu.com/link" in url:
        return url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ("url", "u"):
        if qs.get(key):
            return qs[key][0]
    return url


def parse_search_result_rows(rows: list[dict], client: dict, start_dt: datetime, end_dt: datetime, now: Optional[datetime] = None) -> list[dict]:
    start_dt = _to_client_news_dt(start_dt)
    end_dt = _to_client_news_dt(end_dt)
    now = _to_client_news_dt(now or end_dt or datetime.utcnow())
    out = []
    aliases = [client["name"].lower()] + [a.lower() for a in client.get("aliases", [])]
    for row in rows:
        title = clean_text(row.get("title", ""))
        snippet = clean_text(row.get("snippet", ""))
        url = clean_text(row.get("url", ""))
        blob = f"{title} {snippet}".lower()
        if not title or not url:
            continue
        if not any(alias and alias.lower() in blob for alias in aliases):
            continue
        if any(term.lower() in blob for term in STALE_TERMS):
            continue
        if not any(term.lower() in blob for term in RELEVANCE_TERMS):
            continue
        dt = row.get("published_dt") or _parse_baidu_time(" ".join([row.get("date", ""), snippet]), now)
        if dt:
            dt = _to_client_news_dt(dt)
            if not dt:
                continue
            if dt < (start_dt - timedelta(hours=48)) or dt > (end_dt + timedelta(hours=2)):
                continue
            published_at = dt.strftime("%Y-%m-%d %H:%M")
        else:
            freshness_text = f"{title} {snippet} {row.get('date', '')}"
            if not any(x in freshness_text for x in ("今天", "昨日", "昨天", "小时前", "分钟前")):
                continue
            published_at = ""
        out.append(ClientNewsItem(
            client=client["name"],
            title=title[:120],
            url=url,
            snippet=snippet[:180],
            source=clean_text(row.get("source", "")),
            published_at=published_at,
            query=clean_text(row.get("query", "")),
        ).as_dict())
    return out


def _parse_baidu_html(html: str, query: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    blocks = soup.select("div.result, div.c-container, div.result-op")
    for block in blocks[:8]:
        a = block.find("a", href=True)
        if not a:
            continue
        title = clean_text(a.get_text(" ", strip=True))
        text = clean_text(block.get_text(" ", strip=True))
        snippet = text.replace(title, "", 1).strip()
        rows.append({
            "title": title,
            "url": _unwrap_baidu_url(a.get("href", "")),
            "snippet": snippet,
            "date": snippet,
            "query": query,
        })
    return rows


def _search_baidu(query: str, timeout: float = 6.0) -> list[dict]:
    url = f"https://www.baidu.com/s?wd={quote_plus(query)}&tn=news&rtt=1&bsst=1"
    headers = dict(HEADERS)
    headers.setdefault("Referer", "https://www.baidu.com/")
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return _parse_baidu_html(resp.text, query)


def _cached_search(query: str, cache: dict, ttl_seconds: int, timeout: float) -> list[dict]:
    key = md5_text(query)
    now_ts = time.time()
    queries = cache.setdefault("queries", {})
    cached = queries.get(key)
    if cached and now_ts - float(cached.get("ts", 0)) < ttl_seconds:
        return cached.get("rows", [])
    rows = _search_baidu(query, timeout=timeout)
    queries[key] = {"ts": now_ts, "query": query, "rows": rows[:8]}
    return rows


def collect_client_news(start_dt: datetime, end_dt: datetime, *, global_timeout: float = 75.0, per_query_timeout: float = 6.0, max_queries: int = 35) -> list[dict]:
    deadline = time.monotonic() + global_timeout
    cache = _load_cache()
    found = []
    seen = set()
    try:
        for client, query in iter_client_queries(max_queries=max_queries):
            if time.monotonic() >= deadline:
                break
            try:
                rows = _cached_search(query, cache, ttl_seconds=6 * 3600, timeout=min(per_query_timeout, max(1.0, deadline - time.monotonic())))
            except Exception:
                continue
            for item in parse_search_result_rows(rows, client, start_dt, end_dt, now=end_dt):
                key = (item["client"], item["url"] or md5_text(item["title"]), item["title"])
                if key in seen:
                    continue
                seen.add(key)
                found.append(item)
                if len(found) >= 8:
                    break
            if len(found) >= 8:
                break
    finally:
        _save_cache(cache)
    return found


def format_client_news_ru(items: list[dict]) -> str:
    lines = ["⬛ Новости по нашим клиентам"]
    if not items:
        lines.append("По клиентам из списка свежих релевантных новостей за период не найдено.")
        return "\n\n".join([lines[0], lines[1]])
    for item in items[:6]:
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        reason = _business_relevance_ru(f"{title} {snippet}")
        lines.append(f"▪️ {item.get('client')} — {title}. {reason}\nСсылка: {item.get('url')}")
    return "\n\n".join(lines)


def format_client_news_zh(items: list[dict]) -> str:
    lines = ["⬛ 客户新闻"]
    if not items:
        lines.append("名单内客户在本期未发现新的相关新闻。")
        return "\n\n".join([lines[0], lines[1]])
    for item in items[:6]:
        lines.append(f"▪️ {item.get('client')} — {item.get('title')}。\n链接：{item.get('url')}")
    return "\n\n".join(lines)


def _business_relevance_ru(text: str) -> str:
    low = (text or "").lower()
    if any(x in low for x in ("焦煤", "焦炭", "煤炭", "采购", "招标")):
        return "Для нас важно как сигнал по закупкам угля/кокса и спросу со стороны клиента."
    if any(x in low for x in ("停产", "减产", "环保", "安全", "事故")):
        return "Для нас важно из-за возможного влияния на выпуск стали, потребление сырья и график закупок."
    if any(x in low for x in ("利润", "亏损", "产量", "高炉", "铁水")):
        return "Для нас важно как индикатор финансового состояния, выпуска и сырьевого спроса клиента."
    if any(x in low for x in ("港口", "物流", "运输")):
        return "Для нас важно как возможный сигнал по логистике и поставкам."
    return "Для нас важно как свежий деловой сигнал по клиенту."


def append_client_news_sections(ru: str, zh: str, items: list[dict]) -> tuple[str, str]:
    return f"{ru.rstrip()}\n\n{format_client_news_ru(items)}", f"{zh.rstrip()}\n\n{format_client_news_zh(items)}"


def _parse_cli_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def main():
    parser = argparse.ArgumentParser(description="Collect fresh client news without sending Telegram.")
    parser.add_argument("--start", required=True, help="Report window start, format YYYY-MM-DD HH:MM")
    parser.add_argument("--end", required=True, help="Report window end, format YYYY-MM-DD HH:MM")
    parser.add_argument("--timeout", type=float, default=75.0)
    parser.add_argument("--max-queries", type=int, default=35)
    args = parser.parse_args()
    items = collect_client_news(_parse_cli_dt(args.start), _parse_cli_dt(args.end), global_timeout=args.timeout, max_queries=args.max_queries)
    print(json.dumps(items, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
