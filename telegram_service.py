import re
import httpx
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096

# Tags supported by Telegram Bot API (parse_mode=HTML)
_TG_ALLOWED = frozenset({
    'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del',
    'code', 'pre', 'a', 'tg-spoiler',
})


def _clean_html(text: str) -> str:
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '• ', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(?:ul|ol|h[1-6]|div|span|header|footer|section)[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _sanitize_tg_html(text: str) -> str:
    """Strip HTML tags not supported by Telegram, keep allowed ones intact."""
    def _replace(m: re.Match) -> str:
        inner = m.group(1).strip().lstrip('/')
        tag = inner.split()[0].lower()
        return m.group(0) if tag in _TG_ALLOWED else ''
    return re.sub(r'<(/?\w[^>]*)>', _replace, text)


def _strip_all_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text)


def _split_text(text: str, limit: int = MESSAGE_LIMIT - 100) -> list[str]:
    """Split text at paragraph boundaries if it exceeds limit."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ''
    for para in text.split('\n\n'):
        candidate = (current + '\n\n' + para).lstrip('\n') if current else para
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                parts.append(current)
            current = para[:limit]
    if current:
        parts.append(current)
    return parts or [text[:limit]]


async def _send_message(client: httpx.AsyncClient, base: str, channel_id: str, text: str) -> dict:
    """Send a text message with HTML; fall back to plain text on parse error."""
    safe = _sanitize_tg_html(text)
    resp = await client.post(
        f"{base}/sendMessage",
        json={"chat_id": channel_id, "text": safe, "parse_mode": "HTML"},
    )
    data = resp.json()
    if data.get("ok"):
        return data
    # Telegram rejected HTML — strip all tags and retry
    logger.warning(f"HTML sendMessage failed ({data.get('description')}) — retrying as plain text")
    resp2 = await client.post(
        f"{base}/sendMessage",
        json={"chat_id": channel_id, "text": _strip_all_tags(text)},
    )
    return resp2.json()


async def send_post(
    bot_token: str,
    channel_ids: list[str],
    text: str,
    image_path: Optional[str] = None,
    hashtags: str = "",
) -> dict:
    text = _clean_html(text)
    full_text = f"{text}\n\n{hashtags}" if hashtags else text
    long_text = len(full_text) > CAPTION_LIMIT
    results = {}
    base = f"https://api.telegram.org/bot{bot_token}"

    async with httpx.AsyncClient(timeout=60) as client:
        for channel_id in channel_ids:
            if not channel_id:
                continue
            try:
                local_path = image_path if image_path else None
                sent = False

                if local_path and Path(local_path).exists():
                    logger.info(f"Sending photo {local_path} to {channel_id}")
                    with open(local_path, "rb") as photo:
                        if long_text:
                            # Article: photo first (no caption), then full text
                            resp = await client.post(
                                f"{base}/sendPhoto",
                                data={"chat_id": channel_id},
                                files={"photo": ("image.jpg", photo, "image/jpeg")},
                            )
                        else:
                            caption = _sanitize_tg_html(full_text[:CAPTION_LIMIT])
                            resp = await client.post(
                                f"{base}/sendPhoto",
                                data={
                                    "chat_id": channel_id,
                                    "caption": caption,
                                    "parse_mode": "HTML",
                                },
                                files={"photo": ("image.jpg", photo, "image/jpeg")},
                            )
                    photo_data = resp.json()

                    if not photo_data.get("ok") and not long_text:
                        # Caption HTML failed — retry without parse_mode
                        logger.warning(f"sendPhoto caption HTML failed: {photo_data.get('description')} — retrying plain")
                        with open(local_path, "rb") as photo2:
                            resp2 = await client.post(
                                f"{base}/sendPhoto",
                                data={
                                    "chat_id": channel_id,
                                    "caption": _strip_all_tags(full_text[:CAPTION_LIMIT]),
                                },
                                files={"photo": ("image.jpg", photo2, "image/jpeg")},
                            )
                        photo_data = resp2.json()

                    if photo_data.get("ok"):
                        photo_msg_id = photo_data["result"].get("message_id")
                        if long_text:
                            # Send full text as follow-up (split if > 4000 chars)
                            parts = _split_text(full_text)
                            last_ok = True
                            last_id = photo_msg_id
                            for part in parts:
                                part_data = await _send_message(client, base, channel_id, part)
                                if part_data.get("ok"):
                                    last_id = part_data["result"].get("message_id")
                                else:
                                    logger.error(f"Text part failed: {part_data.get('description')}")
                                    last_ok = False
                                    break
                            if last_ok:
                                results[channel_id] = {"success": True, "message_id": last_id}
                            else:
                                results[channel_id] = {"success": False, "error": "Text message after photo failed"}
                        else:
                            results[channel_id] = {"success": True, "message_id": photo_msg_id}
                        sent = True
                    else:
                        logger.error(f"sendPhoto failed: {photo_data.get('description')} — falling back to text")
                else:
                    if local_path:
                        logger.error(f"Image file not found: {local_path}")

                if not sent:
                    parts = _split_text(full_text)
                    last_ok = True
                    last_id = None
                    for part in parts:
                        part_data = await _send_message(client, base, channel_id, part)
                        if part_data.get("ok"):
                            last_id = part_data["result"].get("message_id")
                        else:
                            logger.error(f"sendMessage failed: {part_data.get('description')}")
                            last_ok = False
                            break
                    if last_ok and last_id:
                        results[channel_id] = {"success": True, "message_id": last_id}
                    else:
                        results[channel_id] = {"success": False, "error": "sendMessage failed"}

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
