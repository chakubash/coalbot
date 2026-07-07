from playwright.sync_api import sync_playwright
import time
import traceback
import urllib.request
import subprocess
from datetime import datetime

MYSTEEL_CDP = "http://127.0.0.1:9222"
SXCOAL_CDP = "http://127.0.0.1:9223"

START_SCRIPT = "/root/coalbot/auth/browser_start.sh"

CONNECT_TIMEOUT_MS = 15000
PAGE_TIMEOUT_MS = 25000
SLEEP_SECONDS = 900
MIN_RESTART_INTERVAL = 180

last_restart_ts = 0


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cdp_alive(cdp_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def start_browsers(reason: str):
    global last_restart_ts

    now = time.time()
    if now - last_restart_ts < MIN_RESTART_INTERVAL:
        print(f"[{ts()}] KEEPALIVE: restart skipped by cooldown. reason={reason}", flush=True)
        return

    last_restart_ts = now
    print(f"[{ts()}] KEEPALIVE: restarting browsers. reason={reason}", flush=True)

    try:
        r = subprocess.run(
            ["bash", START_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=180,
            check=False,
        )
        print(f"[{ts()}] KEEPALIVE: browser_start exit={r.returncode}", flush=True)
        print(r.stdout[-5000:], flush=True)
    except Exception as e:
        print(f"[{ts()}] KEEPALIVE: browser_start FAILED: {repr(e)}", flush=True)
        traceback.print_exc()


def ensure_browsers():
    mysteel_ok = cdp_alive(MYSTEEL_CDP)
    sxcoal_ok = cdp_alive(SXCOAL_CDP)

    if not mysteel_ok or not sxcoal_ok:
        start_browsers(f"mysteel_ok={mysteel_ok}, sxcoal_ok={sxcoal_ok}")
        time.sleep(5)

    return cdp_alive(MYSTEEL_CDP), cdp_alive(SXCOAL_CDP)


def ping_context(cdp_url: str, url: str, name: str):
    if not cdp_alive(cdp_url):
        print(f"[{ts()}] KEEPALIVE {name}: CDP endpoint is not responding: {cdp_url}", flush=True)
        return False

    with sync_playwright() as p:
        browser = None
        page = None
        try:
            browser = p.chromium.connect_over_cdp(cdp_url, timeout=CONNECT_TIMEOUT_MS)

            if not browser.contexts:
                print(f"[{ts()}] KEEPALIVE {name}: no browser contexts", flush=True)
                return False

            context = browser.contexts[0]
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            page.wait_for_timeout(1500)

            print(f"[{ts()}] KEEPALIVE {name}: OK", flush=True)
            return True

        except Exception as e:
            print(f"[{ts()}] KEEPALIVE {name}: ERROR: {repr(e)}", flush=True)
            traceback.print_exc()
            return False

        finally:
            try:
                if page:
                    page.close()
            except Exception:
                pass

            try:
                if browser:
                    browser.close()
            except Exception:
                pass


while True:
    try:
        m_ok, s_ok = ensure_browsers()

        if m_ok:
            ping_context(MYSTEEL_CDP, "https://news.mysteel.com/", "MYSTEEL")
        else:
            print(f"[{ts()}] KEEPALIVE MYSTEEL: still down after restart", flush=True)

        if s_ok:
            ping_context(SXCOAL_CDP, "https://www.sxcoal.com/en", "SXCOAL")
        else:
            print(f"[{ts()}] KEEPALIVE SXCOAL: still down after restart", flush=True)

    except Exception as e:
        print(f"[{ts()}] KEEPALIVE: FATAL LOOP ERROR: {repr(e)}", flush=True)
        traceback.print_exc()

    time.sleep(SLEEP_SECONDS)
