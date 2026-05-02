import asyncio
import httpx
import xml.etree.ElementTree as ET
from datetime import datetime
import logging
import time

logger = logging.getLogger(__name__)

TRACKED = {"USD", "EUR", "CNY", "AED"}
CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
FLAGS = {"USD": "🇺🇸", "EUR": "🇪🇺", "CNY": "🇨🇳", "AED": "🇦🇪"}
_CACHE_TTL = 300  # 5 minutes

_cache: dict = {"data": None, "expires": 0.0}
_cache_lock = asyncio.Lock()


async def _fetch_rates() -> dict:
    """Fetch fresh rates from CBR, no caching."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(CBR_URL)
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    # Use the date from the XML itself, not server clock
    xml_date = root.get("Date", datetime.now().strftime("%d.%m.%Y"))
    rates = {}

    for valute in root.findall("Valute"):
        code = valute.find("CharCode").text
        if code in TRACKED:
            nominal = int(valute.find("Nominal").text)
            value = float(valute.find("Value").text.replace(",", ".")) / nominal
            rates[code] = round(value, 2)

    return {"rates": rates, "date": xml_date, "source": "ЦБ РФ"}


async def refresh_rates() -> None:
    """Force-refresh rates and update cache. Called by scheduler every 5 minutes."""
    global _cache
    try:
        result = await _fetch_rates()
        _cache["data"] = result
        _cache["expires"] = time.monotonic() + _CACHE_TTL
        logger.debug(f"Currency rates refreshed: {result['date']}")
    except Exception as e:
        logger.error(f"Currency refresh error: {e}")


async def get_cbr_rates() -> dict:
    if _cache["data"] and time.monotonic() < _cache["expires"]:
        return _cache["data"]
    async with _cache_lock:
        # Re-check after acquiring lock — another coroutine may have fetched already
        if _cache["data"] and time.monotonic() < _cache["expires"]:
            return _cache["data"]
        try:
            result = await _fetch_rates()
            _cache["data"] = result
            _cache["expires"] = time.monotonic() + _CACHE_TTL
            return result
        except Exception as e:
            logger.error(f"Currency fetch error: {e}")
            if _cache["data"]:
                return _cache["data"]
            return {"rates": {}, "date": "", "source": "error"}


def format_rates_for_post(data: dict) -> str:
    if not data.get("rates"):
        return ""
    lines = [f"💱 Курсы ЦБ РФ на {data['date']}:"]
    for currency in ("USD", "EUR", "CNY", "AED"):
        rate = data["rates"].get(currency)
        if rate is not None:
            lines.append(f"{FLAGS.get(currency, '')} {currency}: {rate} ₽")
    return "\n".join(lines)


def strip_rates_block(text: str) -> str:
    """Remove all appended CBR rates blocks so they can be replaced with fresh data."""
    marker = "\n\n💱 Курсы ЦБ РФ на"
    while True:
        idx = text.find(marker)
        if idx == -1:
            break
        text = text[:idx]
    return text
