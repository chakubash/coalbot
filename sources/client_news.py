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
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote_plus, urlparse, parse_qs
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

from config import DATA_STATE_DIR, HEADERS
from utils import clean_text, md5_text

CLIENT_NEWS_BEIJING_TZ = ZoneInfo("Asia/Shanghai") if ZoneInfo else timezone(timedelta(hours=8))
BOT_LOG_PATH = Path("bot.log")
CACHE_PATH = Path(DATA_STATE_DIR) / "client_news_cache.json"

PRIORITY_CLIENT_NAMES = (
    "Baosteel", "Ansteel", "Valin", "Yongfeng", "Risun", "Ben Steel",
    "Lingyuan Steel", "Liu Steel", "Yaxin", "Lubao", "SUMEC-Esteel", "CIEC",
)

CLIENT_WATCHLIST = [
    {"name": "Baosteel", "aliases": ["宝钢", "宝山钢铁"]},
    {"name": "Ansteel", "aliases": ["鞍钢"]},
    {"name": "Valin", "aliases": ["华菱"]},
    {"name": "Yongfeng", "aliases": ["永锋"]},
    {"name": "Risun", "aliases": ["旭阳"]},
    {"name": "Ben Steel", "aliases": ["本钢"]},
    {"name": "Lingyuan Steel", "aliases": ["凌源钢铁", "凌钢"]},
    {"name": "Liu Steel", "aliases": ["柳钢"]},
    {"name": "Yaxin", "aliases": ["亚新"]},
    {"name": "Lubao", "aliases": ["鲁宝"]},
    {"name": "SUMEC-Esteel", "aliases": ["苏美达", "SUMEC"]},
    {"name": "CIEC", "aliases": ["中煤进出口"]},
    {"name": "Shengmeng-Xiangyu", "aliases": []},
    {"name": "Yuanli", "aliases": []},
    {"name": "Ganglu-AVIC", "aliases": []},
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
    {"name": "Zhuokang", "aliases": []},
]

EN_QUERY_TERMS = ("", "steel", "production", "caster", "rolling mill", "blast furnace", "coke", "coal")
ZH_QUERY_TERMS = ("钢铁", "投产", "产线", "高炉", "焦炭", "焦煤", "采购", "停产", "检修", "环保")

BUSINESS_RELEVANCE_TERMS = (
    # steelmaking / operations
    "steel", "production", "capacity", "commission", "commissioned", "commissioning", "start up", "startup", "starts up",
    "caster", "casting", "slab caster", "continuous caster", "rolling mill", "pipe line", "seamless pipe", "blast furnace",
    "coke oven", "sinter", "maintenance", "shutdown", "outage", "production cut", "environmental", "safety",
    "procurement", "raw material", "iron ore", "coal", "coking coal", "coke", "thermal coal", "port", "logistics",
    "profit", "loss", "investment", "project", "contract", "order", "sms group", "primetals", "hydrogen", "m&a", "restructuring",
    # Chinese equivalents
    "钢铁", "投产", "产线", "连铸", "铸机", "轧机", "钢管", "无缝管", "高炉", "焦炉", "烧结", "检修", "停产",
    "减产", "环保", "安全", "事故", "采购", "原料", "铁矿", "煤炭", "焦煤", "焦炭", "动力煤", "港口", "物流",
    "利润", "亏损", "投资", "项目", "合同", "订单", "重组", "并购", "氢",
)

STALE_TERMS = (
    "公司简介", "企业简介", "公司概况", "百科", "招聘", "周报", "月报", "年度报告", "年报",
    "company profile", "overview", "corporate profile", "about us", "history", "annual report", "weekly", "monthly",
)
PHOTO_TERMS = ("reuters pictures", "reuters photo", "photo", "图片", "图集", "getty images")
STOCK_ONLY_TERMS = ("stock", "share price", "shares", "rating", "price target", "dividend", "股票", "股价", "评级", "目标价")
STOCK_OPERATIONAL_TERMS = ("production", "capacity", "plant", "mill", "blast furnace", "caster", "steel", "profit", "loss", "产量", "高炉", "投产", "钢铁")
MAX_REPORT_URL_LEN = 220


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
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
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


def _log_client_news(message: str):
    try:
        with open(BOT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def _debug_row(client="", alias="", query="", source_adapter="", status="", result_count=0, parsed_count=0,
               accepted_count=0, title="", url="", published_at="", rejection_reason="", elapsed_sec=0.0,
               original_google_url="", resolved_url="") -> dict:
    return {
        "client": client,
        "alias": alias,
        "query": query,
        "source_adapter": source_adapter,
        "status": status,
        "result_count": int(result_count or 0),
        "parsed_count": int(parsed_count or 0),
        "accepted_count": int(accepted_count or 0),
        "title": title,
        "url": url,
        "original_google_url": original_google_url,
        "resolved_url": resolved_url,
        "published_at": published_at,
        "rejection_reason": rejection_reason,
        "elapsed_sec": round(float(elapsed_sec or 0.0), 3),
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


def _client_aliases(client: dict) -> list[str]:
    aliases = [client["name"]] + list(client.get("aliases") or [])
    out = []
    for alias in aliases:
        if alias and alias not in out:
            out.append(alias)
    return out


def iter_client_queries(max_queries: int = 20) -> Iterable[tuple[dict, str, str]]:
    made = 0
    priority = {name: i for i, name in enumerate(PRIORITY_CLIENT_NAMES)}
    clients = sorted(CLIENT_WATCHLIST, key=lambda c: priority.get(c["name"], 999))
    prepared = []
    for client in clients:
        aliases = _client_aliases(client)[:3]
        prepared.append((client, aliases))
    max_rounds = max(
        len(ZH_QUERY_TERMS if any(re.search(r"[\u4e00-\u9fff]", a) for a in aliases) else EN_QUERY_TERMS)
        for _, aliases in prepared
    )
    for round_idx in range(max_rounds):
        for client, aliases in prepared:
            alias = aliases[round_idx % len(aliases)]
            terms = ZH_QUERY_TERMS if re.search(r"[\u4e00-\u9fff]", alias) else EN_QUERY_TERMS
            if round_idx >= len(terms):
                continue
            if made >= max_queries:
                return
            query = f"{alias} {terms[round_idx]}".strip()
            made += 1
            yield client, alias, query


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
    if "today" in text.lower() or "今天" in text:
        return now.replace(hour=12, minute=0, second=0, microsecond=0)
    if "yesterday" in text.lower() or "昨天" in text or "昨日" in text:
        return (now - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    m = re.search(r"(\d+)\s*days?\s*ago", text, flags=re.I)
    if m:
        return now - timedelta(days=int(m.group(1)))
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


def _is_google_news_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return parsed.netloc.endswith("news.google.com")


def _resolve_google_news_url(url: str, timeout: float = 3.0) -> str:
    if not _is_google_news_url(url):
        return url
    try:
        resp = requests.get(url, headers=dict(HEADERS), timeout=timeout, allow_redirects=True)
        final_url = resp.url or ""
        if final_url and not _is_google_news_url(final_url):
            return final_url
    except Exception:
        pass
    return url


def safe_report_url(url: str) -> str:
    url = clean_text(url)
    if not url:
        return ""
    if _is_google_news_url(url):
        url = _resolve_google_news_url(url)
        if _is_google_news_url(url) and len(url) > 80:
            return ""
    if len(url) > MAX_REPORT_URL_LEN:
        return ""
    return url


def _resolved_url_for_row(url: str) -> tuple[str, str]:
    original_google_url = url if _is_google_news_url(url) else ""
    resolved_url = _resolve_google_news_url(url) if original_google_url else url
    if original_google_url and _is_google_news_url(resolved_url):
        return original_google_url, ""
    if len(resolved_url or "") > MAX_REPORT_URL_LEN:
        return original_google_url, ""
    return original_google_url, resolved_url


def _row_rejection_reason(row: dict, client: dict, start_dt: datetime, end_dt: datetime, now: datetime) -> tuple[str, str, str]:
    title = clean_text(row.get("title", ""))
    snippet = clean_text(row.get("snippet", ""))
    url = clean_text(row.get("url", ""))
    source = clean_text(row.get("source", ""))
    blob = f"{title} {snippet} {source} {url}".lower()
    if not title or not url:
        return "missing_title_or_url", "", ""
    original_google_url, resolved_url = _resolved_url_for_row(url)
    if original_google_url and not resolved_url:
        return "google_url_unresolved", "", original_google_url
    if not resolved_url:
        return "url_too_long", "", ""
    aliases = [a.lower() for a in _client_aliases(client)]
    if not any(alias and alias.lower() in blob for alias in aliases):
        return "client_alias_not_found", "", resolved_url
    if any(term.lower() in blob for term in PHOTO_TERMS) and "reuters" in blob:
        return "reuters_photo_page", "", resolved_url
    if any(term.lower() in blob for term in STALE_TERMS):
        return "stale_profile_or_report", "", resolved_url
    if any(term.lower() in blob for term in STOCK_ONLY_TERMS) and not any(term.lower() in blob for term in STOCK_OPERATIONAL_TERMS):
        return "stock_only_without_operations", "", resolved_url
    if any(x in blob for x in ("no direct immediate effect", "no immediate effect", "does not affect current demand", "не несёт прямого", "не влияет на текущий спрос", "скорее фоновый сигнал")):
        return "weak_business_relevance", "", resolved_url
    if not any(term.lower() in blob for term in BUSINESS_RELEVANCE_TERMS):
        return "weak_business_relevance", "", resolved_url

    dt = row.get("published_dt") or _parse_baidu_time(" ".join([row.get("date", ""), snippet, source]), now)
    if dt:
        dt = _to_client_news_dt(dt)
        if not dt:
            return "no_clear_publish_date", "", resolved_url
        inside_window = start_dt <= dt <= end_dt
        same_report_day = dt.date() == end_dt.date()
        if (not inside_window and not same_report_day) or dt > (end_dt + timedelta(hours=2)):
            return "stale_date", "", resolved_url
        return "", dt.strftime("%Y-%m-%d %H:%M"), resolved_url

    freshness_text = f"{title} {snippet} {row.get('date', '')}".lower()
    if not any(x in freshness_text for x in ("today", "今天", "小时前", "分钟前")):
        return "no_clear_publish_date", "", resolved_url
    return "", "", resolved_url


def parse_search_result_rows(rows: list[dict], client: dict, start_dt: datetime, end_dt: datetime,
                             now: Optional[datetime] = None, return_reasons: bool = False):
    start_dt = _to_client_news_dt(start_dt)
    end_dt = _to_client_news_dt(end_dt)
    now = _to_client_news_dt(now or end_dt or datetime.utcnow())
    out = []
    reasons = {}
    for row in rows:
        reason, published_at, resolved_url = _row_rejection_reason(row, client, start_dt, end_dt, now)
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        title = clean_text(row.get("title", ""))
        snippet = clean_text(row.get("snippet", ""))
        url = clean_text(row.get("url", ""))
        out.append(ClientNewsItem(
            client=client["name"],
            title=title[:140],
            url=resolved_url or url,
            snippet=snippet[:220],
            source=clean_text(row.get("source", "")),
            published_at=published_at,
            query=clean_text(row.get("query", "")),
        ).as_dict())
    if return_reasons:
        return out, reasons
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
            "source": clean_text(block.find(class_="c-color-gray").get_text(" ", strip=True)) if block.find(class_="c-color-gray") else "",
            "query": query,
        })
    return rows


def _parse_google_news_rss(xml_text: str, query: str) -> list[dict]:
    rows = []
    try:
        root = ET.fromstring(xml_text or "")
    except Exception:
        return rows
    for item in root.findall(".//item")[:10]:
        title = clean_text(item.findtext("title") or "")
        link = clean_text(item.findtext("link") or "")
        source = clean_text(item.findtext("source") or "")
        pub = clean_text(item.findtext("pubDate") or "")
        snippet = clean_text(item.findtext("description") or "")
        published_dt = None
        if pub:
            try:
                published_dt = parsedate_to_datetime(pub)
            except Exception:
                published_dt = None
        rows.append({
            "title": title,
            "url": link,
            "snippet": snippet,
            "date": pub,
            "source": source,
            "published_dt": published_dt,
            "query": query,
        })
    return rows


def _search_google_news_rss(query: str, timeout: float = 5.0) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    resp = requests.get(url, headers=dict(HEADERS), timeout=timeout)
    resp.raise_for_status()
    return _parse_google_news_rss(resp.text, query)


def _search_baidu(query: str, timeout: float = 5.0) -> list[dict]:
    url = f"https://www.baidu.com/s?wd={quote_plus(query)}&tn=news&rtt=1&bsst=1"
    headers = dict(HEADERS)
    headers.setdefault("Referer", "https://www.baidu.com/")
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return _parse_baidu_html(resp.text, query)


def _cached_search(query: str, cache: dict, ttl_seconds: int, timeout: float) -> list[dict]:
    key = md5_text("baidu:" + query)
    now_ts = time.time()
    queries = cache.setdefault("queries", {})
    cached = queries.get(key)
    if cached and now_ts - float(cached.get("ts", 0)) < ttl_seconds:
        return cached.get("rows", [])
    rows = _search_baidu(query, timeout=timeout)
    queries[key] = {"ts": now_ts, "query": query, "rows": rows[:8]}
    return rows


def _cached_google_search(query: str, cache: dict, ttl_seconds: int, timeout: float) -> list[dict]:
    key = md5_text("google_news_rss:" + query)
    now_ts = time.time()
    queries = cache.setdefault("queries", {})
    cached = queries.get(key)
    if cached and now_ts - float(cached.get("ts", 0)) < ttl_seconds:
        return cached.get("rows", [])
    rows = _search_google_news_rss(query, timeout=timeout)
    queries[key] = {"ts": now_ts, "query": query, "rows": rows[:10]}
    return rows


def _rejection_summary(reasons: dict) -> str:
    return ";".join(f"{k}:{v}" for k, v in sorted((reasons or {}).items()))


def _append_query_debug(debug_rows: Optional[list], *, client: dict, alias: str, query: str, source_adapter: str,
                        status: str, rows: list, accepted: list, reasons: dict, elapsed: float):
    if debug_rows is None:
        return
    shown_url = accepted[0].get("url", "") if accepted else (rows[0].get("url", "") if rows else "")
    original_google_url = shown_url if _is_google_news_url(shown_url) else ""
    resolved_url = accepted[0].get("url", "") if accepted else ""
    debug_rows.append(_debug_row(
        client=client.get("name", ""),
        alias=alias,
        query=query,
        source_adapter=source_adapter,
        status=status,
        result_count=len(rows or []),
        parsed_count=len(rows or []),
        accepted_count=len(accepted or []),
        title=(accepted[0].get("title", "") if accepted else (rows[0].get("title", "") if rows else "")),
        url=shown_url,
        original_google_url=original_google_url,
        resolved_url=resolved_url,
        published_at=(accepted[0].get("published_at", "") if accepted else ""),
        rejection_reason=_rejection_summary(reasons),
        elapsed_sec=elapsed,
    ))


def collect_client_news(start_dt: datetime, end_dt: datetime, *, global_timeout: float = 60.0, per_query_timeout: float = 5.0,
                        max_queries: int = 20, max_items: int = 5, debug_rows: Optional[list] = None,
                        run_dir: str = "") -> list[dict]:
    started = time.monotonic()
    deadline = started + global_timeout
    cache = _load_cache()
    found = []
    seen = set()
    seen_clients = set()
    if debug_rows is None:
        debug_rows = []
    _log_client_news(f"CLIENT_NEWS_START run_dir={run_dir or ''}")
    try:
        for client, alias, query in iter_client_queries(max_queries=max_queries):
            if time.monotonic() >= deadline:
                _log_client_news(f"CLIENT_NEWS_TIMEOUT elapsed_sec={time.monotonic() - started:.3f}")
                debug_rows.append(_debug_row(client=client.get("name", ""), alias=alias, query=query, status="timeout", elapsed_sec=time.monotonic() - started))
                break
            for adapter, search_fn in (("google_news_rss", _cached_google_search), ("baidu", _cached_search)):
                if time.monotonic() >= deadline:
                    _log_client_news(f"CLIENT_NEWS_TIMEOUT elapsed_sec={time.monotonic() - started:.3f}")
                    break
                q_started = time.monotonic()
                rows = []
                accepted = []
                reasons = {}
                try:
                    timeout = min(per_query_timeout, max(1.0, deadline - time.monotonic()))
                    rows = search_fn(query, cache, ttl_seconds=6 * 3600, timeout=timeout)
                    accepted, reasons = parse_search_result_rows(rows, client, start_dt, end_dt, now=end_dt, return_reasons=True)
                    status = "accepted" if accepted else "rejected"
                except Exception as exc:
                    reasons = {"error": 1}
                    status = "error"
                    debug_rows.append(_debug_row(
                        client=client.get("name", ""), alias=alias, query=query, source_adapter=adapter,
                        status="error", rejection_reason=str(exc)[:180], elapsed_sec=time.monotonic() - q_started,
                    ))
                    continue
                _append_query_debug(
                    debug_rows, client=client, alias=alias, query=query, source_adapter=adapter,
                    status=status, rows=rows, accepted=accepted, reasons=reasons, elapsed=time.monotonic() - q_started,
                )
                for item in accepted:
                    dedupe_key = (item["client"], md5_text(re.sub(r"\s+", " ", item["title"].lower())))
                    url_key = item.get("url") or dedupe_key
                    key = (item["client"], url_key)
                    if key in seen or dedupe_key in seen:
                        debug_rows.append(_debug_row(
                            client=item.get("client", ""), alias=alias, query=query, source_adapter=adapter,
                            status="rejected", title=item.get("title", ""), url=item.get("url", ""),
                            resolved_url=item.get("url", ""), rejection_reason="duplicate_story",
                            elapsed_sec=time.monotonic() - q_started,
                        ))
                        continue
                    if item["client"] in seen_clients:
                        debug_rows.append(_debug_row(
                            client=item.get("client", ""), alias=alias, query=query, source_adapter=adapter,
                            status="rejected", title=item.get("title", ""), url=item.get("url", ""),
                            resolved_url=item.get("url", ""), rejection_reason="duplicate_client",
                            elapsed_sec=time.monotonic() - q_started,
                        ))
                        continue
                    seen.add(key)
                    seen.add(dedupe_key)
                    seen_clients.add(item["client"])
                    found.append(item)
                    if len(found) >= max_items:
                        debug_rows.append(_debug_row(
                            client=item.get("client", ""), alias=alias, query=query, source_adapter=adapter,
                            status="skipped", rejection_reason="over_total_limit",
                            elapsed_sec=time.monotonic() - q_started,
                        ))
                        break
                if len(found) >= max_items:
                    break
            if len(found) >= max_items:
                break
    except Exception as exc:
        _log_client_news(f"CLIENT_NEWS_ERROR error={str(exc)[:200]}")
    finally:
        _save_cache(cache)
        _log_client_news(f"CLIENT_NEWS_DONE elapsed_sec={time.monotonic() - started:.3f} found={len(found)} debug_rows={len(debug_rows)}")
    return found[:max_items]


def _business_relevance_ru(text: str) -> str:
    low = (text or "").lower()
    if any(x in low for x in ("caster", "casting", "rolling mill", "pipe", "blast furnace", "投产", "产线", "连铸", "轧机", "高炉", "无缝管")):
        return "это важно для оценки производственных мощностей и потенциального спроса на сырьё."
    if any(x in low for x in ("sms group", "primetals", "order", "contract", "合同", "订单")):
        return "это полезно как сигнал инвестиций и обновления производственной базы клиента."
    if any(x in low for x in ("焦煤", "焦炭", "煤炭", "采购", "招标", "coal", "coke", "coking coal", "procurement")):
        return "это важно как сигнал по закупкам угля/кокса и спросу со стороны клиента."
    if any(x in low for x in ("停产", "减产", "环保", "安全", "事故", "maintenance", "shutdown", "environmental", "safety")):
        return "это важно из-за возможного влияния на выпуск стали, потребление сырья и график закупок."
    if any(x in low for x in ("利润", "亏损", "产量", "profit", "loss", "production")):
        return "это важно как индикатор финансового состояния, выпуска и сырьевого спроса клиента."
    if any(x in low for x in ("港口", "物流", "运输", "port", "logistics", "transport")):
        return "это полезно как сигнал по логистике и поставкам."
    return "это полезно как свежий деловой сигнал по клиенту."


def format_client_news_ru(items: list[dict]) -> str:
    lines = ["⬛ Иные новости"]
    if not items:
        lines.append("Свежих релевантных новостей по отслеживаемым компаниям за период не найдено.")
        return "\n\n".join([lines[0], lines[1]])
    for item in items[:6]:
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        reason = _business_relevance_ru(f"{title} {snippet}")
        block = f"— {item.get('client')} — {title}; {reason}"
        url = safe_report_url(item.get("url", ""))
        if url:
            block += f"\nСсылка: {url}"
        lines.append(block)
    return "\n\n".join(lines)


def format_client_news_zh(items: list[dict]) -> str:
    lines = ["⬛ 其他新闻"]
    if not items:
        lines.append("本期未发现跟踪公司相关的新消息。")
        return "\n\n".join([lines[0], lines[1]])
    for item in items[:6]:
        block = f"— {item.get('client')} — {item.get('title')}。"
        url = safe_report_url(item.get("url", ""))
        if url:
            block += f"\n链接：{url}"
        lines.append(block)
    return "\n\n".join(lines)


def append_client_news_sections(ru: str, zh: str, items: list[dict]) -> tuple[str, str]:
    return f"{ru.rstrip()}\n\n{format_client_news_ru(items)}", f"{zh.rstrip()}\n\n{format_client_news_zh(items)}"


def _parse_cli_dt(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def main():
    parser = argparse.ArgumentParser(description="Collect fresh client news without sending Telegram.")
    parser.add_argument("--start", required=True, help="Report window start, format YYYY-MM-DD HH:MM")
    parser.add_argument("--end", required=True, help="Report window end, format YYYY-MM-DD HH:MM")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-queries", type=int, default=20)
    args = parser.parse_args()
    debug_rows = []
    items = collect_client_news(
        _parse_cli_dt(args.start), _parse_cli_dt(args.end),
        global_timeout=args.timeout, max_queries=args.max_queries, debug_rows=debug_rows,
    )
    print(json.dumps({"items": items, "debug_rows": debug_rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
