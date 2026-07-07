from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

MYSTEEL_CDP = "http://127.0.0.1:9222"
SXCOAL_CDP = "http://127.0.0.1:9223"


def _open_via_cdp(cdp_url: str, url: str):
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)

        if not browser.contexts:
            raise RuntimeError(f"No live browser context on {cdp_url}")

        context = browser.contexts[0]
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(4000)

        try:
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(1200)
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(1200)
        except Exception:
            pass

        html = page.content()
        final_url = page.url

        try:
            page.close()
        except Exception:
            pass

        return html, final_url


def get_mysteel_html(url: str):
    return _open_via_cdp(MYSTEEL_CDP, url)


def get_sxcoal_html(url: str):
    return _open_via_cdp(SXCOAL_CDP, url)


def looks_like_login_required(html: str) -> bool:
    text = html.lower()
    return any(x in text for x in [
        "login", "sign in", "登录", "password",
        "the login information is invalid", "login again"
    ])


def looks_like_paywall_sxcoal(html: str) -> bool:
    text = html.lower()
    return any(x in text for x in [
        "subscription", "full access", "subscribe", "buy this article"
    ])


def looks_like_forbidden(html: str) -> bool:
    text = html.lower()
    return any(x in text for x in [
        "403 forbidden", "openresty", "access denied", "forbidden"
    ])


def extract_full_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    selectors = [
        "article",
        "div.article-content",
        "div.article_content",
        "div.content",
        "div.news-content",
        "div.news_content",
        "div#article_content",
        "div#content",
        "div.detail-content",
        "div.detail_content",
        "div.txt-content",
        "div.text",
        "div.article",
        "section",
    ]

    for sel in selectors:
        blocks = soup.select(sel)
        for b in blocks:
            text = b.get_text(" ", strip=True)
            if len(text) > 300:
                return text[:12000]

    return soup.get_text(" ", strip=True)[:12000]
