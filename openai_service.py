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


def _text_width(draw, text, font):
    try:
        return draw.textlength(text, font=font)
    except AttributeError:
        return draw.textsize(text, font=font)[0]


def _wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _add_branding(filepath: Path, headline: str):
    try:
        from PIL import Image, ImageDraw, ImageFont
        import re

        img = Image.open(filepath).convert("RGB")
        w, h = img.size

        # Find bold font
        font_paths = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        ]
        font_path = None
        for fp in font_paths:
            if Path(fp).exists():
                font_path = fp
                break

        hook_size = max(54, w // 16)
        brand_size = max(30, w // 30)
        if font_path:
            font_hook = ImageFont.truetype(font_path, hook_size)
            font_brand = ImageFont.truetype(font_path, brand_size)
        else:
            font_hook = font_brand = ImageFont.load_default()

        # Extract hook: first sentence, strip HTML, max 50 chars
        clean = re.sub(r"<[^>]+>", "", headline).strip()
        first = re.split(r"[.!?\n]", clean)[0].strip()
        hook = first[:50] + ("…" if len(first) > 50 else "")

        # Wrap hook text to fit 88% of width
        dummy = ImageDraw.Draw(img)
        lines = _wrap_text(dummy, hook, font_hook, w * 0.88)

        line_h = int(hook_size * 1.25)
        block_h = len(lines) * line_h
        pad = int(h * 0.03)

        # Position: centered vertically in upper 55%
        block_top = max(pad, int(h * 0.28) - block_h // 2)
        block_bottom = block_top + block_h

        # ── Step 1: dark semi-transparent box behind hook text ────────────────
        box_img = img.convert("RGBA")
        box_ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        box_draw = ImageDraw.Draw(box_ov)
        margin_x = int(w * 0.05)
        box_draw.rectangle(
            [(margin_x, block_top - pad), (w - margin_x, block_bottom + pad)],
            fill=(0, 0, 0, 175),
        )
        img = Image.alpha_composite(box_img, box_ov).convert("RGB")

        # ── Step 2: draw hook lines centered ─────────────────────────────────
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(lines):
            lw = _text_width(draw, line, font_hook)
            x = (w - lw) / 2
            y = block_top + i * line_h
            # Shadow
            draw.text((x + 2, y + 2), line, fill=(0, 0, 0, 160), font=font_hook)
            # Text
            draw.text((x, y), line, fill=(255, 255, 255), font=font_hook)

        # ── Step 3: dark gradient at bottom for SEVEN-X ───────────────────────
        bot_ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        bot_draw = ImageDraw.Draw(bot_ov)
        grad_start = int(h * 0.82)
        for y in range(grad_start, h):
            alpha = int(210 * (y - grad_start) / (h - grad_start))
            bot_draw.line([(0, y), (w, y)], fill=(8, 20, 12, alpha))
        img = Image.alpha_composite(img.convert("RGBA"), bot_ov).convert("RGB")

        # ── Step 4: SEVEN-X centered at bottom ───────────────────────────────
        draw = ImageDraw.Draw(img)
        bw = _text_width(draw, "SEVEN-X", font_brand)
        draw.text(((w - bw) / 2, h - brand_size - int(h * 0.04)),
                  "SEVEN-X", fill=(82, 183, 136), font=font_brand)

        img.save(filepath, "JPEG", quality=90)
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
