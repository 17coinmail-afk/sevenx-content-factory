import httpx
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def send_post(
    bot_token: str,
    channel_ids: list[str],
    text: str,
    image_path: str = None,
    hashtags: str = "",
) -> dict:
    full_text = f"{text}\n\n{hashtags}" if hashtags else text
    results = {}
    base = f"https://api.telegram.org/bot{bot_token}"

    async with httpx.AsyncClient(timeout=60) as client:
        for channel_id in channel_ids:
            if not channel_id:
                continue
            try:
                local_path = image_path if image_path else None

                if local_path and Path(local_path).exists():
                    with open(local_path, "rb") as photo:
                        resp = await client.post(
                            f"{base}/sendPhoto",
                            data={"chat_id": channel_id, "caption": full_text, "parse_mode": "HTML"},
                            files={"photo": ("image.jpg", photo, "image/jpeg")},
                        )
                else:
                    resp = await client.post(
                        f"{base}/sendMessage",
                        json={"chat_id": channel_id, "text": full_text, "parse_mode": "HTML"},
                    )

                resp.raise_for_status()
                data = resp.json()

                if data.get("ok"):
                    results[channel_id] = {
                        "success": True,
                        "message_id": data["result"]["message_id"],
                    }
                else:
                    results[channel_id] = {"success": False, "error": data.get("description")}

            except Exception as e:
                logger.error(f"Telegram error for {channel_id}: {e}")
                results[channel_id] = {"success": False, "error": str(e)}

    return results


async def test_connection(bot_token: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
            data = resp.json()
            if data.get("ok"):
                return {"success": True, "bot_name": data["result"]["username"]}
            return {"success": False, "error": data.get("description", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": str(e)}
