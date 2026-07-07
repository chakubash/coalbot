import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    {"name": "Valin", "aliases": ["华菱"]},
    {"name": "Yongfeng", "aliases": ["永锋"]},
    {"name": "Risun", "aliases": ["旭阳"]},
    {"name": "Ben Steel", "aliases": ["本钢"]},
    {"name": "Lingyuan Steel", "aliases": ["凌源钢铁", "凌钢"]},
    {"name": "Liu Steel", "aliases": ["柳钢"]},
    {"name": "Yaxin", "aliases": ["亚新"]},
    {"name": "Lubao", "aliases": ["鲁宝"]},
    {"name": "SUMEC-Esteel", "aliases": ["苏美达", "SUMEC"]},
    {"name": "CIEC", "aliases": ["中煤进出口", "中国煤炭进出口"]},
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
QUERY_TERMS = ("煤炭", "焦煤", "焦炭", "钢铁", "采购", "港口", "事故", "停产", "环保", "亏损", "利润", "产量")
RELEVANCE_TERMS = QUERY_TERMS + (
    "煤", "焦", "高炉", "铁水", "炼钢", "供应", "合同", "招标", "运输", "物流", "安全", "检查", "减产", "复产"
)
STALE_TERMS = ("公司简介", "企业简介", "公司概况", "百科", "招聘", "周报", "月报", "年度报告", "年报")
CACHE_PATH = Path(DATA_STATE_DIR) / "client_news_cache.json"
BOT_LOG_PATH = Path("bot.log")


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


def _log_client_news(message: str):
    try:
        with BOT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def _debug_row(client: str, alias: str, query: str, status: str, result_count: int = 0, parsed_count: int = 0, accepted_count: int = 0, rejection_reason: str = "", elapsed_sec: float = 0.0) -> dict:
    return {
        "client": client,
        "alias": alias,
        "query": query,
        "status": status,
        "result_count": result_count,
        "parsed_count": parsed_count,
        "accepted_count": accepted_count,
        "rejection_reason": rejection_reason,
        "elapsed_sec": round(float(elapsed_sec or 0), 3),
    }


def _format_rejection_reasons(reasons: dict) -> str:
    if not reasons:
        return ""
    return ";".join(f"{k}:{v}" for k, v in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])))


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


def iter_client_queries(max_queries: int = 20) -> Iterable[tuple[dict, str, str]]:
    made = 0
    for client in CLIENT_WATCHLIST:
        aliases = _client_search_aliases(client)
        terms = ("煤炭", "焦炭", "钢铁") if client.get("aliases") else ("钢铁",)
        for alias in aliases:
            for term in terms:
                if made >= max_queries:
                    return
                made += 1
                yield client, alias, f"{alias} {term}"


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


def parse_search_result_rows(rows: list[dict], client: dict, start_dt: datetime, end_dt: datetime, now: Optional[datetime] = None, *, return_reasons: bool = False):
    now = now or end_dt or datetime.utcnow()
    out = []
    reasons = {}
    aliases = [client["name"].lower()] + [a.lower() for a in client.get("aliases", [])]

    def reject(reason: str):
        reasons[reason] = reasons.get(reason, 0) + 1

    for row in rows:
        title = clean_text(row.get("title", ""))
        snippet = clean_text(row.get("snippet", ""))
        url = clean_text(row.get("url", ""))
        blob = f"{title} {snippet}".lower()
        if not title or not url:
            reject("missing_title_or_url")
            continue
        if not any(alias and alias.lower() in blob for alias in aliases):
            reject("client_alias_not_found")
            continue
        if any(term.lower() in blob for term in STALE_TERMS):
            reject("stale_profile_or_report")
            continue
        if not any(term.lower() in blob for term in RELEVANCE_TERMS):
            reject("not_business_relevant")
            continue
        dt = row.get("published_dt") or _parse_baidu_time(" ".join([row.get("date", ""), snippet]), now)
        if dt:
            if dt < (start_dt - timedelta(hours=48)) or dt > (end_dt + timedelta(hours=2)):
                reject("outside_freshness_window")
                continue
            published_at = dt.strftime("%Y-%m-%d %H:%M")
        else:
            freshness_text = f"{title} {snippet} {row.get('date', '')}"
            if not any(x in freshness_text for x in ("今天", "今日", "昨日", "昨天", "小时前", "分钟前")):
                reject("no_fresh_date_signal")
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
    if return_reasons:
        return out, reasons
    return out


def _parse_baidu_html(html: str, query: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    selectors = [
        "div.result", "div.c-container", "div.result-op",
        "div.news-list li", "div#content_left > div", "article",
    ]
    blocks = []
    for selector in selectors:
        blocks.extend(soup.select(selector))
    if not blocks:
        blocks = soup.find_all(["div", "li", "article"], limit=30)

    seen = set()
    for block in blocks[:30]:
        a = block.find("a", href=True)
        if not a:
            continue
        title = clean_text(a.get_text(" ", strip=True) or a.get("title", ""))
        href = _unwrap_baidu_url(a.get("href", ""))
        if not title or not href:
            continue
        key = title + "|" + href
        if key in seen:
            continue
        seen.add(key)
        text = clean_text(block.get_text(" ", strip=True))
        snippet = text.replace(title, "", 1).strip()
        source = ""
        source_tag = block.select_one(".c-color-gray, .c-source, .news-source, .source")
        if source_tag:
            source = clean_text(source_tag.get_text(" ", strip=True))
        rows.append({
            "title": title,
            "url": href,
            "snippet": snippet,
            "date": snippet,
            "source": source,
            "query": query,
        })
        if len(rows) >= 10:
            break
    return rows


def _search_baidu(query: str, timeout: float = 6.0) -> list[dict]:
    url = f"https://www.baidu.com/s?wd={quote_plus(query)}&tn=news&rtt=1&bsst=1"
    headers = dict(HEADERS)
    headers.setdefault("Referer", "https://www.baidu.com/")
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return _parse_baidu_html(resp.text, query)


def _search_baidu_browser(query: str, timeout: float = 5.0) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    url = f"https://www.baidu.com/s?wd={quote_plus(query)}&tn=news&rtt=1&bsst=1"
    browser = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            html = page.content()
            return _parse_baidu_html(html, query)
    except Exception:
        return []
    finally:
        try:
            if browser:
                browser.close()
        except Exception:
            pass


def _cached_search(query: str, cache: dict, ttl_seconds: int, timeout: float) -> list[dict]:
    key = md5_text(query)
    now_ts = time.time()
    queries = cache.setdefault("queries", {})
    cached = queries.get(key)
    if cached and now_ts - float(cached.get("ts", 0)) < ttl_seconds:
        return cached.get("rows", [])
    try:
        rows = _search_baidu(query, timeout=timeout)
    except Exception:
        rows = []
    if not rows:
        rows = _search_baidu_browser(query, timeout=timeout)
    queries[key] = {"ts": now_ts, "query": query, "rows": rows[:10]}
    return rows


def collect_client_news(start_dt: datetime, end_dt: datetime, *, global_timeout: float = 60.0, per_query_timeout: float = 5.0, max_queries: int = 20, debug_rows: Optional[list] = None) -> list[dict]:
    deadline = time.monotonic() + global_timeout
    cache = _load_cache()
    found = []
    seen = set()
    timed_out = False
    _log_client_news("CLIENT_NEWS_START")
    try:
        for client, alias, query in iter_client_queries(max_queries=max_queries):
            if time.monotonic() >= deadline:
                timed_out = True
                if debug_rows is not None:
                    debug_rows.append(_debug_row(client["name"], alias, query, "timeout", rejection_reason="global_timeout"))
                break
            t0 = time.monotonic()
            status = "ok"
            rows = []
            accepted = []
            reasons = {}
            try:
                timeout = min(per_query_timeout, max(0.5, deadline - time.monotonic()))
                rows = _cached_search(query, cache, ttl_seconds=6 * 3600, timeout=timeout)
                accepted, reasons = parse_search_result_rows(rows, client, start_dt, end_dt, now=end_dt, return_reasons=True)
            except Exception as exc:
                status = "error"
                reasons = {f"error:{type(exc).__name__}": 1}
            elapsed = time.monotonic() - t0
            if elapsed >= per_query_timeout:
                status = "timeout" if not rows else status
            if debug_rows is not None:
                debug_rows.append(_debug_row(
                    client["name"],
                    alias,
                    query,
                    status,
                    result_count=len(rows),
                    parsed_count=len(rows),
                    accepted_count=len(accepted),
                    rejection_reason=_format_rejection_reasons(reasons),
                    elapsed_sec=elapsed,
                ))
            for item in accepted:
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
        if timed_out:
            _log_client_news(f"CLIENT_NEWS_TIMEOUT found={len(found)}")
        _log_client_news(f"CLIENT_NEWS_DONE found={len(found)}")
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
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-queries", type=int, default=20)
    args = parser.parse_args()
    items = collect_client_news(_parse_cli_dt(args.start), _parse_cli_dt(args.end), global_timeout=args.timeout, max_queries=args.max_queries)
    print(json.dumps(items, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
