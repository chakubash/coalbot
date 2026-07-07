
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from config import BEIJING_TZ

_fx_cache = {"updated_at": None, "cny_to_usd": None}


def fetch_ecb_rates():
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        rates = {}
        for elem in root.iter():
            currency = elem.attrib.get("currency")
            rate = elem.attrib.get("rate")
            if currency and rate:
                rates[currency] = float(rate)
        return rates
    except Exception:
        return {}


def cny_to_usd_rate():
    global _fx_cache
    now = datetime.now(BEIJING_TZ)

    if _fx_cache["updated_at"] and _fx_cache["cny_to_usd"] is not None:
        if now - _fx_cache["updated_at"] < timedelta(hours=6):
            return _fx_cache["cny_to_usd"]

    rates = fetch_ecb_rates()
    eur_usd = rates.get("USD")
    eur_cny = rates.get("CNY")
    if not eur_usd or not eur_cny:
        return _fx_cache["cny_to_usd"]

    rate = eur_usd / eur_cny
    _fx_cache["updated_at"] = now
    _fx_cache["cny_to_usd"] = rate
    return rate


def format_price_with_usd(value, currency, unit=""):
    try:
        numeric_value = float(str(value).replace(",", ""))
    except Exception:
        return f"{value} {currency}{unit}"

    currency = (currency or "").upper()

    if currency == "CNY":
        rate = cny_to_usd_rate()
        if rate:
            usd_value = numeric_value * rate
            return f"{numeric_value:.2f} CNY{unit} (≈ {usd_value:.2f} USD{unit})"
        return f"{numeric_value:.2f} CNY{unit}"

    if currency in ["USD", "$"]:
        return f"{numeric_value:.2f} USD{unit}"

    return f"{numeric_value:.2f} {currency}{unit}"
