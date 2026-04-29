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


async def get_cbr_rates() -> dict:
    if _cache["data"] and time.monotonic() < _cache["expires"]:
        return _cache["data"]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(CBR_URL)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        rates = {}

        for valute in root.findall("Valute"):
            code = valute.find("CharCode").text
            if code in TRACKED:
                nominal = int(valute.find("Nominal").text)
                value = float(valute.find("Value").text.replace(",", ".")) / nominal
                rates[code] = round(value, 2)

        result = {
            "rates": rates,
            "date": datetime.now().strftime("%d.%m.%Y"),
            "source": "ЦБ РФ",
        }
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
    for currency, rate in data["rates"].items():
        flag = FLAGS.get(currency, "")
        lines.append(f"{flag} {currency}: {rate} ₽")
    return "\n".join(lines)


def strip_rates_block(text: str) -> str:
    """Remove a previously appended CBR rates block so it can be replaced with fresh data."""
    marker = "\n\n💱 Курсы ЦБ РФ на"
    idx = text.find(marker)
    return text[:idx] if idx != -1 else text
