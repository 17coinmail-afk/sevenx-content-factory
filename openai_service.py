import os
import uuid
import json
import httpx
import logging
from pathlib import Path
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "images"))
IMAGES_DIR.mkdir(exist_ok=True, parents=True)

STYLE_PROMPTS = {
    "expert": "Экспертный стиль: профессиональный тон, конкретные факты и цифры, демонстрация компетентности компании.",
    "casual": "Живой разговорный стиль: как будто объясняешь другу, с реальными примерами из жизни предпринимателя.",
    "case": 'Формат кейса: "Ситуация клиента → Проблема → Как Seven-X решила → Конкретный результат". Реалистичная история.',
    "faq": "Формат FAQ: Популярный вопрос о ВЭД/международных платежах → Чёткий развёрнутый ответ от эксперта Seven-X.",
}

IMAGE_PROMPT_BASE = (
    "Professional business digital illustration for a VED (foreign trade) financial services company. "
    "Dark green (#1a3328) and teal (#2d6a4f) color palette, modern corporate aesthetic. "
    "Abstract geometric shapes, global finance and international trade symbolism, currency exchange, "
    "world map elements, clean minimal design. High quality render. Absolutely NO text or letters in the image."
)


async def generate_text_variants(
    topic: str,
    style: str,
    brand_voice: str,
    currency_text: str,
    client: AsyncOpenAI,
) -> list[dict]:
    style_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS["expert"])
    currency_block = f"\n\nВключи в пост актуальные курсы валют:\n{currency_text}" if currency_text else ""

    user_prompt = f"""Напиши 3 совершенно разных варианта Telegram-поста на тему: "{topic}"

{style_prompt}{currency_block}

Требования:
- Каждый вариант уникален по структуре и подаче
- Эмодзи использовать уместно, не перегружать
- Длина: 200–900 символов
- Хэштеги: 3–5 штук, mix русских и английских

Ответ строго в JSON:
{{
  "variants": [
    {{"text": "текст поста", "hashtags": "#хэштег1 #хэштег2 #хэштег3"}},
    {{"text": "текст поста", "hashtags": "#хэштег1 #хэштег2 #хэштег3"}},
    {{"text": "текст поста", "hashtags": "#хэштег1 #хэштег2 #хэштег3"}}
  ]
}}"""

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": brand_voice},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.88,
    )

    result = json.loads(response.choices[0].message.content)
    return result.get("variants", [])


async def generate_image(topic: str, post_text: str, client: AsyncOpenAI) -> str:
    prompt = f"{IMAGE_PROMPT_BASE} Topic context: '{topic}'."

    response = await client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1,
    )

    image_url = response.data[0].url
    filename = f"{uuid.uuid4()}.png"
    filepath = IMAGES_DIR / filename

    async with httpx.AsyncClient(timeout=60) as http:
        img_resp = await http.get(image_url)
        img_resp.raise_for_status()
        filepath.write_bytes(img_resp.content)

    return f"/images/{filename}"
