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

FORMAT_PROMPTS = {
    "article": """\
ФОРМАТ: ЭКСПЕРТНАЯ СТАТЬЯ (1800–2600 символов)

Структура — строго соблюдать, между каждым блоком пустая строка:

[эмодзи] <b>Заголовок</b> — 1 строка: либо главный инсайт, либо ключевая проблема (не риторический вопрос)

Вступление (2–3 предложения): почему тема важна прямо сейчас, цифра или факт, который задаёт масштаб проблемы

<b>Блок 1 — контекст</b> (3–4 предложения): как устроен рынок/механизм, что именно не работает и почему — конкретика, никаких общих слов

<b>Блок 2 — подводные камни</b> (3–4 предложения): типичные ошибки или нюанс, о котором 90% предпринимателей не знают — тут читатель должен подумать «а я так и делал»

<b>Блок 3 — решение Seven-X</b> (3–4 предложения): конкретные шаги, инструменты, цифры — не «мы помогаем», а «мы делаем вот это за вот столько времени»

[эмодзи] Итог + CTA (2 строки): главная мысль одной фразой, затем живой призыв с контактом Артёма

Текст должен читаться как полезный гайд, а не реклама. Читатель забирает пользу даже без обращения в Seven-X.""",

    "promo": """\
ФОРМАТ: ПРОДАЮЩИЙ ПОСТ (400–650 символов)

Структура — строго:
Строка 1 (КРЮЧОК): одно предложение, которое останавливает скролл. Начни с цифры, парадокса, или прямого удара в боль. БЕЗ риторических вопросов. БЕЗ «Вы знали, что...»

Следующие 2–3 предложения: боль → поворот → конкретное решение с цифрой или фактом Seven-X

Финал: живой CTA — одна строка с контактом, без «обращайтесь к нам»

ПРИНЦИПЫ:
— Каждое слово оправдано: убери всё, что не добавляет смысл
— Цифры, детали, конкретные механики = доверие
— Читатель должен почувствовать: «это прямо про мою ситуацию»
— Ноль канцелярита, ноль корпоративного языка""",
}

STYLE_PROMPTS = {
    "expert": """\
Тон: авторитетный инсайдер — говорит прямо, знает специфику рынка лучше читателя, не боится называть вещи своими именами.
— Используй специфику: конкретные суммы, механики, названия инструментов (Alipay, WeChat, агентская схема, НДС-возврат)
— Если в теме есть парадокс или противоречие — вытащи его на первый план
— CTA: деловой и прямой («Артём разберёт вашу схему за 15 минут — напишите»)""",

    "casual": """\
Тон: предприниматель — предпринимателю, как сообщение в бизнес-чате: знающий человек делится опытом без пафоса.
— Короткие предложения, живые обороты, допустима лёгкая ирония
— Пишешь как будто сам через это прошёл и теперь рассказываешь приятелю
— CTA: мягкий, личный («Напишите Артёму — без лишних слов разберётся»)""",

    "case": """\
Тон: история, которую интересно дочитать до конца — конкретная ситуация, реальный результат.
— Конкретная ситуация клиента: товар, сумма, дедлайн, что поставлено на кон (без имён компаний)
— Структура: задача → нестандартный ход Seven-X → результат цифрами
— Детали правдоподобные и специфичные — это делает историю живой
— CTA: «Похожая задача? Артём обсудит вашу ситуацию»""",

    "faq": """\
Тон: честный и прямой — вопрос, который реально задают, и конкретный ответ без уклонений.
❓ <b>Вопрос</b>: острый, немного провокационный — читатель думает «я тоже это хотел спросить»
💡 <b>Ответ</b>: конкретная механика с цифрами, без общих фраз, с чётким объяснением как это работает в Seven-X
— Финал: короткий живой CTA""",
}

SYSTEM_PROMPT = """\
Ты — редактор Telegram-канала Seven-X, ведущего платёжного агента для ВЭД.

ПРОФИЛЬ АУДИТОРИИ: предприниматели 30–55 лет, которые ввозят товары из Китая, ОАЭ, Европы. Их боли: банки отказывают в платежах, санкции блокируют переводы, теряются деньги на конвертации, непонятно как работать легально.

ТВОЯ ЗАДАЧА: каждый текст должен делать одно из трёх:
1. Научить конкретному инструменту (читатель забирает реальную пользу)
2. Снять страх или закрыть возражение
3. Показать возможность, о которой читатель не догадывался

ФАКТЫ Seven-X — используй конкретику, не общие слова:
• 12 лет на рынке, $4 млрд+ оборот импортных сделок
• 40+ компаний-плательщиков по всему миру
• Валюты: USD, EUR, CNY (юань), AED (дирхам) — без ограничений
• Рубли утром → платёжное поручение вечером того же дня
• Санкционные товары — без российского следа
• Возврат до 40% НДС из Китая рублями в РФ
• Выкуп валютной выручки: доплата 1–3% к рыночному курсу
• Переводы: Alipay, WeChat, наличные, крипта
• Агентская схема и договор поставки — на выбор клиента
• Менеджер на связи 24/7
• Контакт: Артём, +7 967 202-55-54, artem@seven-x.ru

ЗАПРЕЩЕНО: «осуществлять», «предоставляем услуги», «взаимодействие», «компания готова помочь» и любой корпоративный канцелярит.
РАЗРЕШЕНО: числа, факты, конкретные механики, живые слова, сравнения.
HTML: <b>жирный</b> только для заголовков блоков и 1–2 ключевых цифры. Эмодзи: 3–5, строго уместно. Пустая строка между блоками."""

_PEXELS_QUERIES = {
    "китай":   "china business trade finance",
    "юань":    "chinese yuan currency money",
    "дирхам":  "dubai UAE business gold luxury",
    "санкц":   "international trade business global",
    "ндс":     "tax refund money finance",
    "alipay":  "mobile payment technology digital",
    "wechat":  "digital payment mobile",
    "крипт":   "cryptocurrency bitcoin blockchain",
    "валют":   "currency exchange money international",
    "вэд":     "cargo shipping containers international",
    "выручк":  "business profit revenue growth",
    "агент":   "business partnership handshake contract",
    "платёж":  "bank transfer payment wire",
    "скорост": "business speed fast delivery",
}

_IMAGE_STYLES = [
    "cinematic photorealistic, dramatic lighting",
    "sleek 3D render, dark studio background",
    "professional digital art, vibrant colors",
    "moody corporate photography style",
    "modern minimalist illustration, bold shapes",
]

_TOPIC_VISUALS = {
    "китай":    "Shanghai skyline, container ships, yuan coins, dragon motif",
    "юань":     "Chinese yuan banknotes fanned out, gold bars, red and gold",
    "дирхам":   "Dubai Burj Khalifa at night, UAE dirham gold coins, luxury",
    "санкц":    "globe with glowing trade routes, barrier breaking, freedom path",
    "ндс":      "money flowing back into hands, percentage symbol, tax refund",
    "alipay":   "smartphone with QR code glow, digital payment beam, tech",
    "wechat":   "mobile wallet, chat bubble with money, digital transfer",
    "крипт":    "golden bitcoin, blockchain network nodes, crypto glow",
    "валют":    "multiple currency banknotes fan, exchange rate display",
    "вэд":      "cargo ship at sea, world map routes glowing, customs gate",
    "выручк":   "money flowing into funnel, profit growth arrow, business win",
    "агент":    "handshake over globe, contract document, trust symbol",
    "платёж":   "lightning-fast wire transfer, globe with currency symbols",
    "скорост":  "speedometer at max, rocket launch, fast delivery concept",
}


def _build_image_prompt(topic: str) -> str:
    import random
    style = random.choice(_IMAGE_STYLES)
    topic_lower = topic.lower()
    extra = ""
    for key, visual in _TOPIC_VISUALS.items():
        if key in topic_lower:
            extra = f" Featured elements: {visual}."
            break
    return (
        f"{style}. A powerful business image for a Russian foreign-trade payment company. "
        f"Theme: '{topic}'.{extra} "
        f"Color palette: deep forest green #0f2018, gold #c9a84c, emerald #52b788. "
        f"International finance, global money transfers, premium corporate feel. "
        f"NO text, NO letters, NO words anywhere in the image."
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
    contact_info: str = "",
    post_format: str = "promo",
) -> list[dict]:
    format_prompt = FORMAT_PROMPTS.get(post_format, FORMAT_PROMPTS["promo"])
    style_prompt = STYLE_PROMPTS.get(style, STYLE_PROMPTS["expert"])
    currency_block = f"\n\nВключи в пост актуальные курсы валют:\n{currency_text}" if currency_text else ""
    contact_block = f"\n\nКонтакт для CTA в посте: {contact_info}" if contact_info else ""

    system = brand_voice.strip() if brand_voice.strip() else SYSTEM_PROMPT

    if post_format == "article":
        variant_instructions = """\
Требования к трём вариантам — каждый берёт свой угол атаки:
— Вариант 1: угол «механика» — объясни как именно это работает изнутри, технические детали доступным языком
— Вариант 2: угол «история» — начни с конкретной ситуации клиента, разверни как нарратив
— Вариант 3: угол «деньги» — покажи через цифры: сколько теряют без этого знания и сколько получают с ним"""
    else:
        variant_instructions = """\
Требования к трём вариантам — каждый бьёт в другую точку:
— Вариант 1: начни с парадокса или шокирующего факта (то, во что трудно поверить, но это правда)
— Вариант 2: начни с конкретной боли — ситуации, которую читатель прямо сейчас переживает
— Вариант 3: начни с цифры или результата — дай сначала вывод, потом объяснение"""

    user_prompt = f"""Напиши 3 варианта поста на тему: «{topic}»

{format_prompt}

Тон:
{style_prompt}{currency_block}{contact_block}

{variant_instructions}

Каждый вариант — своя точка входа, свои факты, своя эмоция. Не повторяй одни и те же предложения и цифры в разных вариантах.

Ответ строго в JSON (ничего лишнего):
{{
  "variants": [
    {{"text": "текст поста с HTML-тегами <b></b> и пустыми строками между абзацами", "hashtags": "#тег1 #тег2 #тег3", "image_hook": "3-5 слов на картинку"}},
    {{"text": "...", "hashtags": "...", "image_hook": "..."}},
    {{"text": "...", "hashtags": "...", "image_hook": "..."}}
  ]
}}

image_hook — максимум 5 слов, провокационный крючок для картинки (только заглавные буквы, без знаков препинания). Должен заставить остановиться при скролле."""

    temp = 0.95 if post_format == "article" else 0.90
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=temp,
    )

    raw = response.choices[0].message.content
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        try:
            import re as _re
            m = _re.search(r'\{.*\}', raw, _re.DOTALL)
            result = json.loads(m.group()) if m else {}
        except Exception:
            logger.error(f"Failed to parse AI response as JSON: {raw[:200]}")
            return []

    variants = result.get("variants") or result.get("Variants") or result.get("posts") or []
    if not variants and isinstance(result, list):
        variants = result
    if not variants:
        logger.warning(f"AI returned no variants. Keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
    return variants


async def generate_image(topic: str, post_text: str, client: AsyncOpenAI) -> str:
    prompt = _build_image_prompt(topic)

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


_font_cache: dict = {}

# Candidate font paths in priority order — no module-level I/O, purely lazy
_BOLD_CANDIDATES = [
    Path(__file__).parent / "fonts" / "Bold.ttf",
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
]
_REG_CANDIDATES = [
    Path(__file__).parent / "fonts" / "Regular.ttf",
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


def _get_font(size: int, bold: bool = True):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]

    from PIL import ImageFont

    candidates = _BOLD_CANDIDATES if bold else _REG_CANDIDATES
    font = None
    for p in candidates:
        try:
            if p.exists():
                font = ImageFont.truetype(str(p), size)
                logger.info(f"Font loaded: {p.name} size={size}")
                break
        except Exception as e:
            logger.debug(f"Font {p}: {e}")

    if font is None:
        logger.warning(f"No TrueType font found (bold={bold}), text will look tiny")
        font = ImageFont.load_default()

    _font_cache[key] = font
    return font


def _tw(draw, text, font):
    try:
        return int(draw.textlength(text, font=font))
    except AttributeError:
        return draw.textsize(text, font=font)[0]


def _wrap(draw, text, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if _tw(draw, cand, font) <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def _add_branding(filepath: Path, headline: str, contact_info: str = "", hook: str = ""):
    try:
        from PIL import Image, ImageDraw, ImageFont
        import re

        img = Image.open(filepath).convert("RGB")
        W, H = img.size

        title_sz = max(72, W // 10)
        sub_sz   = max(20, W // 44)
        brand_sz = max(26, W // 34)
        font_t = _get_font(title_sz, bold=True)
        font_s = _get_font(sub_sz,   bold=False)
        font_b = _get_font(brand_sz, bold=True)

        is_tt = isinstance(font_t, ImageFont.FreeTypeFont)
        logger.info(f"Branding start: {W}x{H} TrueType={is_tt} path={_BOLD_CANDIDATES[0]}")

        if hook and hook.strip():
            title = hook.strip().upper()
        else:
            clean = re.sub(r"<[^>]+>", "", headline).strip()
            first = re.split(r"[.!?\n]", clean)[0].strip()
            title = first.upper()

        px    = int(W * 0.06)   # left margin — all text starts here
        max_w = W - px * 2

        # Pre-wrap to know total text height
        _tmp_draw = ImageDraw.Draw(img)
        lines = _wrap(_tmp_draw, title, font_t, max_w)[:3]
        lh      = int(title_sz * 1.22)
        title_h = len(lines) * lh
        sub_h   = sub_sz + int(H * 0.01)
        brand_h = brand_sz
        pad     = int(H * 0.03)

        # Total panel height: pad + title + gap + sub + gap + brand + pad
        panel_h = pad + title_h + int(pad * 0.6) + sub_h + int(pad * 0.4) + brand_h + pad
        panel_h = max(panel_h, int(H * 0.28))
        panel_top = H - panel_h

        # ── Soft fade above panel, then solid panel ────────────────────────
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        fade_h = int(H * 0.10)
        for i in range(fade_h):
            a = int(160 * (i / fade_h))
            od.line([(0, panel_top - fade_h + i), (W, panel_top - fade_h + i)],
                    fill=(4, 12, 8, a))
        od.rectangle([(0, panel_top), (W, H)], fill=(6, 16, 10, 242))  # near-solid
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        # Brand separator line at top of panel
        sep = max(4, int(H * 0.004))
        draw.rectangle([(0, panel_top), (W, panel_top + sep)], fill=(107, 191, 142))

        # ── Text layout — strictly left-aligned from px ───────────────────
        y = panel_top + sep + pad

        # Headline: white, ALL CAPS, large
        for line in lines:
            if is_tt:
                draw.text((px, y), line, fill=(255, 255, 255), font=font_t,
                          stroke_width=max(2, title_sz // 24), stroke_fill=(0, 0, 0))
            else:
                draw.text((px + 2, y + 2), line, fill=(0, 0, 0), font=font_t)
                draw.text((px, y), line, fill=(255, 255, 255), font=font_t)
            y += lh

        y += int(pad * 0.5)

        # Contact line: gray, small
        contact_line = contact_info.strip() if contact_info.strip() else "seven-x.ru  ·  Артём: +7 967 202-55-54"
        draw.text((px, y), contact_line, fill=(160, 160, 160), font=font_s)
        y += sub_h

        # sevenx wordmark logo — paste PNG if available, fallback to text
        _WORDMARK = Path(__file__).parent / "static" / "brand" / "wordmark-dark.png"
        _painted_logo = False
        if _WORDMARK.exists():
            try:
                wm = Image.open(_WORDMARK).convert("RGBA")
                # Invert dark logo to white so it shows on dark panel
                from PIL import ImageOps
                r, g, b, a = wm.split()
                rgb_inv = ImageOps.invert(Image.merge("RGB", (r, g, b)))
                wm = Image.merge("RGBA", (*rgb_inv.split(), a))
                target_h = max(brand_sz, int(H * 0.04))
                wm_w = int(wm.width * target_h / wm.height)
                wm = wm.resize((wm_w, target_h), Image.LANCZOS)
                base = img.convert("RGBA")
                base.paste(wm, (px, y), wm)
                img = base.convert("RGB")
                draw = ImageDraw.Draw(img)
                _painted_logo = True
            except Exception as _le:
                logger.debug(f"Logo paste failed: {_le}")
        if not _painted_logo:
            draw.text((px, y), "sevenx", fill=(107, 191, 142), font=font_b)

        # Small brand mark in top-right corner (светлый зеленый знак)
        _MARK = Path(__file__).parent / "static" / "brand" / "mark-green.png"
        if _MARK.exists():
            try:
                from PIL import ImageOps
                mk = Image.open(_MARK).convert("RGBA")
                mark_h = max(int(H * 0.07), 48)
                mk_w = int(mk.width * mark_h / mk.height)
                mk = mk.resize((mk_w, mark_h), Image.LANCZOS)
                # Slight transparency so it doesn't overpower the photo
                r, g, b, a = mk.split()
                a = a.point(lambda x: int(x * 0.80))
                mk = Image.merge("RGBA", (r, g, b, a))
                base2 = img.convert("RGBA")
                mark_x = W - mk_w - int(W * 0.04)
                mark_y = int(H * 0.03)
                base2.paste(mk, (mark_x, mark_y), mk)
                img = base2.convert("RGB")
            except Exception as _me:
                logger.debug(f"Mark paste failed: {_me}")

        img.save(filepath, "JPEG", quality=93)
        logger.info(f"Branding OK: '{title[:40]}' {len(lines)} lines, panel_h={panel_h}")
    except Exception as e:
        logger.error(f"Branding failed: {e}", exc_info=True)


async def fetch_image_pexels(topic: str, api_key: str, contact_info: str = "", hook: str = "") -> str:
    import random
    topic_lower = topic.lower()
    query = "international business finance"
    for key, q in _PEXELS_QUERIES.items():
        if key in topic_lower:
            query = q
            break

    logger.info(f"Pexels search: '{query}' for topic '{topic[:60]}'")
    headers = {"Authorization": api_key}
    search_url = (
        f"https://api.pexels.com/v1/search"
        f"?query={urllib.parse.quote(query)}&per_page=10&orientation=square"
    )

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(search_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    photos = data.get("photos", [])
    if not photos:
        raise ValueError(f"Pexels: no photos for '{query}'")

    photo = random.choice(photos[:min(6, len(photos))])
    img_url = photo["src"]["large"]

    filename = f"{uuid.uuid4()}.jpg"
    filepath = IMAGES_DIR / filename

    async with httpx.AsyncClient(timeout=60) as http:
        img_resp = await http.get(img_url)
        img_resp.raise_for_status()
        filepath.write_bytes(img_resp.content)

    _add_branding(filepath, topic, contact_info=contact_info, hook=hook)
    logger.info(f"Pexels image saved: {filename}")
    return f"/images/{filename}"


async def generate_image_pollinations(topic: str, post_text: str, contact_info: str = "", hook: str = "") -> str:
    import random
    prompt  = _build_image_prompt(topic)
    encoded = urllib.parse.quote(prompt)
    seed    = random.randint(1, 999_999)
    logger.info(f"Image prompt (seed={seed}): {prompt[:120]}")
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1024&height=1024&nologo=true&model=flux&seed={seed}"
    )

    filename = f"{uuid.uuid4()}.jpg"
    filepath = IMAGES_DIR / filename

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
        resp = await http.get(url)
        resp.raise_for_status()
        if len(resp.content) < 5000:
            raise ValueError(f"Pollinations returned too-small response ({len(resp.content)} bytes)")
        filepath.write_bytes(resp.content)

    _add_branding(filepath, post_text or topic, contact_info=contact_info, hook=hook)
    return f"/images/{filename}"
