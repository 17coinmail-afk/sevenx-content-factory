import os
import uuid
import json
import httpx
import logging
import urllib.parse
from pathlib import Path
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

IMAGES_DIR = Path(os.getenv("IMAGES_DIR", "images"))
IMAGES_DIR.mkdir(exist_ok=True, parents=True)

STYLE_PROMPTS = {
    "expert": """\
Экспертный продающий стиль.
Структура:
1. Первая строка — острый заголовок: боль/вопрос + эмодзи
2. 2-3 конкретных преимущества Seven-X (цифры, скорость, выгода)
3. Призыв к действию — написать Артёму

Используй <b>жирный</b> для заголовка и ключевых фактов.
Эмодзи — только по делу, не более 4 штук.""",

    "casual": """\
Живой разговорный стиль — как друг, который в теме.
Структура:
1. Реальная ситуация / проблема предпринимателя — с иронией или сочувствием
2. «Вот как это решает Seven-X» — просто и конкретно
3. Мягкий призыв — «напиши Артёму, расскажет»

Используй <b>жирный</b> для ключевых моментов. Разговорные обороты, без канцелярита.""",

    "case": """\
Формат мини-кейса.
Структура:
1. <b>Ситуация:</b> конкретная проблема реального клиента (без имён)
2. <b>Решение:</b> что сделала Seven-X — конкретные шаги
3. <b>Результат:</b> цифры, скорость, выгода
4. CTA: «У вас похожая задача? → Артём»

Всё конкретно, правдоподобно, без воды.""",

    "faq": """\
Формат вопрос-ответ.
Структура:
1. <b>❓ Вопрос</b> — реальный вопрос предпринимателя о ВЭД/платежах
2. <b>💡 Ответ</b> — чёткий, экспертный, с конкретикой от Seven-X
3. Финал: «Остались вопросы? Пишите Артёму»

Вопрос должен быть острым, ответ — исчерпывающим.""",
}

SYSTEM_PROMPT = """\
Ты — опытный копирайтер Telegram-канала компании Seven-X, ведущего платёжного агента для ВЭД.

ФАКТЫ о компании (используй их):
• 12 лет на рынке, $4 млрд+ оборот импортных сделок
• 40+ компаний-плательщиков по всему миру
• Валюты: USD, EUR, CNY (юань), AED (дирхам)
• Рубли утром → платёжное поручение вечером
• Агентская схема и договор поставки
• Санкционные товары — без российского следа
• Выкуп валютной выручки с доплатой 1–3%
• Возврат до 40% НДС из Китая рублями в РФ
• Переводы: Alipay, WeChat, наличные, крипта
• Контакт: Артём, +7 967 202-55-54, artem@seven-x.ru
• Менеджер на связи 24/7

ПРАВИЛА:
- Пиши на русском
- Форматирование HTML: <b>жирный</b>, <i>курсив</i>
- Длина поста: 300–600 символов (это лимит подписи к фото в Telegram)
- Хэштеги: 3–4 штуки, отдельной строкой в поле hashtags
- Каждый вариант — уникальная структура и подача
- Всегда заканчивай CTA с контактом Артёма"""

IMAGE_PROMPT_BASE = (
    "Professional business illustration for a Russian foreign trade payment company. "
    "Deep forest green (#0f2018) background, gold and emerald accent colors. "
    "Concepts: international money transfer, global trade routes, currency exchange. "
    "Style: modern flat design with subtle geometric patterns, globe or world map elements, "
    "currency symbols (¥ $ € ₽), clean corporate look. High quality. NO text or letters."
)

DEFAULT_MODELS = {
    "https://api.groq.com/openai/v1": "llama-3.3-70b-versatile",
    "https://api.deepseek.com": "deepseek-chat",
}


async def generate_text_variants(
    topic: str,
    style: str,
    brand_voice: str,
    currency_text: str,
    client: AsyncOpenAI,
    model: str = "gpt-4o",
) -> list[dict]:
    style_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS["expert"])
    currency_block = f"\n\nВключи в пост актуальные курсы валют:\n{currency_text}" if currency_text else ""

    system = brand_voice.strip() if brand_voice.strip() else SYSTEM_PROMPT

    user_prompt = f"""Напиши 3 разных продающих Telegram-поста на тему: «{topic}»

{style_prompt}{currency_block}

Ответ строго в JSON (ничего лишнего):
{{
  "variants": [
    {{"text": "текст поста с HTML-тегами", "hashtags": "#тег1 #тег2 #тег3"}},
    {{"text": "текст поста с HTML-тегами", "hashtags": "#тег1 #тег2 #тег3"}},
    {{"text": "текст поста с HTML-тегами", "hashtags": "#тег1 #тег2 #тег3"}}
  ]
}}"""

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.85,
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


def _add_branding(filepath: Path, headline: str):
    try:
        from PIL import Image, ImageDraw, ImageFont
        import re

        img = Image.open(filepath).convert("RGBA")
        w, h = img.size

        # Dark gradient overlay at bottom 38%
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw_ov = ImageDraw.Draw(overlay)
        band_start = int(h * 0.62)
        for y in range(band_start, h):
            alpha = int(200 * (y - band_start) / (h - band_start))
            draw_ov.line([(0, y), (w, y)], fill=(8, 20, 12, alpha))

        result = Image.alpha_composite(img, overlay).convert("RGB")
        draw = ImageDraw.Draw(result)

        # Try to find a bold font
        font_paths = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
        ]
        font_large = font_small = None
        for fp in font_paths:
            if Path(fp).exists():
                try:
                    font_large = ImageFont.truetype(fp, size=max(36, w // 22))
                    font_small = ImageFont.truetype(fp, size=max(26, w // 30))
                    break
                except Exception:
                    pass
        if font_large is None:
            font_large = font_small = ImageFont.load_default()

        # Strip HTML tags for display
        clean = re.sub(r"<[^>]+>", "", headline).strip()
        # Take first line up to 55 chars
        first_line = clean.split("\n")[0][:55]
        if len(clean.split("\n")[0]) > 55:
            first_line += "…"

        # Bottom branding bar
        margin = int(w * 0.05)
        brand_y = h - int(h * 0.09)
        draw.text((margin, brand_y), "SEVEN-X", fill=(82, 183, 136), font=font_small)

        # Headline above branding
        headline_y = brand_y - int(h * 0.11)
        draw.text((margin, headline_y), first_line, fill=(255, 255, 255), font=font_large)

        result.save(filepath, "JPEG", quality=88)
    except Exception as e:
        logger.warning(f"Branding overlay failed: {e}")


async def generate_image_pollinations(topic: str, post_text: str) -> str:
    prompt = f"{IMAGE_PROMPT_BASE} Topic: {topic}."
    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&model=flux"

    filename = f"{uuid.uuid4()}.jpg"
    filepath = IMAGES_DIR / filename

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
        resp = await http.get(url)
        resp.raise_for_status()
        if len(resp.content) < 5000:
            raise ValueError(f"Pollinations returned too-small response ({len(resp.content)} bytes)")
        filepath.write_bytes(resp.content)

    _add_branding(filepath, post_text or topic)
    return f"/images/{filename}"
