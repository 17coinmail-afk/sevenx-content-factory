import os
import re
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
ФОРМАТ: ЭКСПЕРТНАЯ СТАТЬЯ (2000–2800 символов)

Первая строка — <b>жирный заголовок</b>: одна строка, главная мысль одним ударом. Цифра, факт или парадокс. Не риторический вопрос.

Пустая строка.

2–3 предложения: почему эта тема важна прямо сейчас, масштаб проблемы в деньгах или времени.

Пустая строка.

Абзац 2–3 предложения: как устроена эта проблема изнутри — детали, которые знают только практики ВЭД.

Пустая строка.

Абзац 3–4 предложения: типичная ошибка или ловушка — конкретный сценарий с суммой потерь.

Пустая строка.

Абзац 3–4 предложения: как Seven-X решает — точная механика, цифры, скорость.

Пустая строка.

<b>Итоговая мысль одной фразой</b> — жирным. То, что читатель перешлёт коллеге.

Пустая строка.

Финал: «Напишите нашему менеджеру» + контакт.

⛔ НЕЛЬЗЯ писать в тексте слова-заголовки секций: «Вступление», «Заголовок», «Контекст», «Подводные камни», «Решение», «Итог», «Блок», «CTA», «Основная часть» — это только схема, читатель их не должен видеть.""",

    "promo": """\
ФОРМАТ: ЭКСПЕРТНЫЙ ПОСТ-КЕЙС (1500–2000 символов)

Первая строка — <b>жирный заголовок</b>: боль читателя или факт, который останавливает скролл.

Пустая строка.

Абзац 3–4 предложения: конкретная знакомая ситуация — товар, страна, проблема с платежом, деньги на кону.

Пустая строка.

Абзац 3–4 предложения: как Seven-X решает эту задачу — механика, цифры, скорость.

Пустая строка.

Абзац 2–3 предложения: что клиент получает конкретно — время, деньги, безопасность сделки.

Пустая строка.

Финал: «Напишите нашему менеджеру» + контакт.

⛔ НЕЛЬЗЯ писать в тексте слова-заголовки секций: «Заголовок», «Блок», «CTA», «Итог» — это только схема, читатель их не должен видеть.""",

    "poll": """\
ФОРМАТ: ПОСТ-ОПРОС (700–1000 символов)

Первая строка — <b>жирный вопрос или провокационный факт</b>: острый, практически значимый для импортёра.

Пустая строка.

2–3 предложения контекста: почему этот вопрос горит прямо сейчас.

Пустая строка.

Варианты ответа — 4 штуки, каждый на отдельной строке с эмодзи-цифрой:
1️⃣ Вариант А (конкретный и узнаваемый)
2️⃣ Вариант Б
3️⃣ Вариант В
4️⃣ Вариант Г

Пустая строка.

Финал: «Голосуйте в комментариях» + для нестандартных ситуаций — контакт менеджера.

⛔ НЕЛЬЗЯ писать в тексте слова-заголовки секций.""",

    "story": """\
ФОРМАТ: ИСТОРИЯ / ИСТОРИЧЕСКИЙ КЕЙС (1500–2000 символов)

Первая строка — <b>жирный заголовок</b>: дата, имя или шокирующий факт — то, что заставляет читать дальше.

Пустая строка.

Завязка 2–3 предложения: кто, где, когда, что поставлено на кон. Конкретика — без общих слов.

Пустая строка.

Развитие 3–4 предложения: детали, суммы, нестандартный ход, поворот сюжета.

Пустая строка.

Развязка 2–3 предложения: результат в цифрах, чем закончилось.

Пустая строка.

Мораль для сегодняшнего дня — 1–2 предложения: что эта история говорит предпринимателю в 2025 году.

Пустая строка.

Финал: открытый вопрос аудитории или лёгкий CTA — история должна быть ценна сама по себе.

⛔ НЕЛЬЗЯ писать в тексте слова-заголовки секций.""",

    "engagement": """\
ФОРМАТ: ВОВЛЕКАЮЩИЙ ПОСТ (900–1300 символов)

Первая строка — <b>жирная провокация или неожиданное утверждение</b>: заставляет остановиться.

Пустая строка.

2–3 предложения контекста: почему эта тема актуальна прямо сейчас для аудитории.

Пустая строка.

Главный вопрос к аудитории — конкретный, из личного опыта: на него хочется ответить.

Пустая строка.

Позиция Seven-X — 2–3 предложения: мнение или неожиданный факт из практики (не реклама!).

Пустая строка.

Финал: «Напишите в комментариях» — без агрессивного CTA. Для тех, кто хочет разобраться лично — контакт менеджера.

⛔ НЕЛЬЗЯ писать в тексте слова-заголовки секций.""",
}

STYLE_PROMPTS = {
    "expert": """\
Тон: авторитетный инсайдер — говорит прямо, знает специфику рынка лучше читателя, не боится называть вещи своими именами.
— Используй специфику: конкретные суммы, механики, названия инструментов (Alipay, WeChat, агентская схема, НДС-возврат)
— Если в теме есть парадокс или противоречие — вытащи его на первый план
— CTA: деловой и прямой («наш менеджер разберёт вашу схему за 15 минут — напишите»)""",

    "casual": """\
Тон: предприниматель — предпринимателю, как сообщение в бизнес-чате: знающий человек делится опытом без пафоса.
— Короткие предложения, живые обороты, допустима лёгкая ирония
— Пишешь как будто сам через это прошёл и теперь рассказываешь приятелю
— CTA: мягкий, личный («Напишите нашему менеджеру — без лишних слов разберётся»)""",

    "case": """\
Тон: история, которую интересно дочитать до конца — конкретная ситуация, реальный результат.
— Конкретная ситуация клиента: товар, сумма, дедлайн, что поставлено на кон (без имён компаний)
— Структура: задача → нестандартный ход Seven-X → результат цифрами
— Детали правдоподобные и специфичные — это делает историю живой
— CTA: «Похожая задача? Напишите — менеджер обсудит вашу ситуацию»""",

    "faq": """\
Тон: честный и прямой — вопрос, который реально задают, и конкретный ответ без уклонений.
❓ <b>Вопрос</b>: острый, немного провокационный — читатель думает «я тоже это хотел спросить»
💡 <b>Ответ</b>: конкретная механика с цифрами, без общих фраз, с чётким объяснением как это работает в Seven-X
— Финал: «напишите вашему менеджеру» + контакт""",
}

SYSTEM_PROMPT = """\
Ты — редактор Telegram-канала Seven-X, ведущего платёжного агента для ВЭД. Пишешь как деловой журналист: жёстко, конкретно, без корпоративного мусора.

АУДИТОРИЯ: предприниматели 30–55 лет, импортируют из Китая, ОАЭ, Европы. Боль: банк заблокировал перевод, платёж завис на три недели, деньги теряются на конвертации.

ГОЛОС И СТИЛЬ:
— Уверенный инсайдер — знает рынок ВЭД изнутри, говорит как практик, а не как пресс-служба
— Первое предложение бьёт в болевую точку без разгона и прелюдий
— Каждый абзац — одна чёткая мысль, конкретная цифра или факт
— Ритм: короткие удары чередуются с развёрнутым анализом
— Никакого «мы рады», «осуществляем», «готовы помочь» — это убивает доверие мгновенно

СТРУКТУРА ПОСТА — обязательна:
1. Первая строка — <b>жирный заголовок</b>: суть в одном ударе
2. Пустая строка между каждым абзацем
3. Минимум 3 смысловых абзаца: проблема → механика → результат для клиента
4. Финал — CTA с контактом

HTML: используй ТОЛЬКО <b>жирный</b> и <i>курсив</i>.
НЕ используй другие HTML-теги — они сломают отображение в Telegram.

ОРФОГРАФИЯ: перед финальным ответом внимательно проверь каждое слово в каждом посте. Ни одной опечатки, ни одной грамматической ошибки — это профессиональный канал.

ФАКТЫ Seven-X — только конкретика:
• 12 лет на рынке, $4 млрд+ оборот импортных сделок
• 40+ компаний-плательщиков по всему миру — чистая история у каждой
• Валюты: USD, EUR, CNY, AED — платим туда, куда банки отказывают
• Рубли утром → платёжное поручение вечером того же дня
• Санкционные товары — без российского следа, без риска для клиента
• Возврат до 40% НДС из Китая рублями прямо в РФ
• Выкуп валютной выручки: доплата 1–3% сверх рыночного курса
• Переводы: Alipay, WeChat, наличные, крипта — любым путём
• Агентская схема или договор поставки — клиент выбирает
• Менеджер 24/7 — живой человек, берёт трубку ночью

В CTA: «ваш менеджер» или «наш менеджер» — имена людей не упоминать.

ЗАПРЕЩЕНО: «осуществляем», «предоставляем услуги», «взаимодействие», «готовы помочь», «в рамках», «данный», любой канцелярит.
ЗАПРЕЩЕНО: риторические вопросы в начале («Вы знали, что...?», «Задумывались ли вы...?»).
ЗАПРЕЩЕНО: общие заявления без цифр («быстро», «надёжно», «выгодно» — без доказательства).
ЗАПРЕЩЕНО: слова-заголовки секций в тексте («Вступление», «CTA», «Блок», «Итог» и подобные)."""

_SECTION_LABEL_LINE = re.compile(
    r'^\s*\**\s*(?:ЗАГОЛОВОК|ВСТУПЛЕНИЕ|КОНТЕКСТ|ПОДВОДНЫЕ\s+КАМНИ|РЕШЕНИЕ'
    r'|ИТОГ(?:\s*\+\s*\S+)?|БЛОК\s*\d*|CTA|ОСНОВН\S*(?:\s+\S+)?'
    r'|ТЕМА|ВЫВОД|SUMMARY|CONCLUSION|ВВЕДЕНИЕ)\s*\**\s*[:\-—]?\s*$',
    re.IGNORECASE,
)
_SECTION_LABEL_PREFIX = re.compile(
    r'^\s*\**\s*(?:ЗАГОЛОВОК|ВСТУПЛЕНИЕ|КОНТЕКСТ|ПОДВОДНЫЕ\s+КАМНИ|РЕШЕНИЕ'
    r'|ИТОГ(?:\s*\+\s*\S+)?|БЛОК\s*\d*|CTA|ОСНОВН\S*(?:\s+\S+)?'
    r'|ТЕМА|ВЫВОД)\s*\**\s*[:\-—]\s+',
    re.IGNORECASE,
)


def _clean_generated_text(text: str) -> str:
    """Strip AI section labels leaked into post, convert **markdown** bold to HTML."""
    # Markdown bold → <b> (Llama/DeepSeek often output ** instead of HTML)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Markdown italic → <i> (only when clearly delimited)
    text = re.sub(r'(?<!\*)\*([^\*\n]{2,})\*(?!\*)', r'<i>\1</i>', text)

    lines = text.split('\n')
    cleaned = []
    for line in lines:
        if _SECTION_LABEL_LINE.match(line):
            continue  # pure section-label line — drop it
        line = _SECTION_LABEL_PREFIX.sub('', line, count=1)  # strip inline prefix
        cleaned.append(line)

    result = '\n'.join(cleaned)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


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


def _build_image_prompt(topic: str, hook: str = "") -> str:
    import random
    style = random.choice(_IMAGE_STYLES)
    topic_lower = topic.lower()
    extra = ""
    for key, visual in _TOPIC_VISUALS.items():
        if key in topic_lower:
            extra = f" Featured elements: {visual}."
            break
    # Hook makes the prompt unique per post — prevents Pollinations cache hits
    hook_part = f" Visual concept: {hook.strip()}." if hook and hook.strip() else ""
    return (
        f"{style}. A powerful business image for a Russian foreign-trade payment company. "
        f"Theme: '{topic}'.{extra}{hook_part} "
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
    contact_block = f"\n\nКонтакт для CTA в посте: {contact_info}" if contact_info else ""

    if brand_voice.strip():
        system = SYSTEM_PROMPT + "\n\n---\nДОПОЛНИТЕЛЬНЫЕ ИНСТРУКЦИИ РЕДАКТОРА:\n" + brand_voice.strip()
    else:
        system = SYSTEM_PROMPT

    if post_format == "article":
        variant_instructions = """\
Три варианта — три разных угла, три разных читателя:
— Вариант 1 «механика»: разбери как устроено изнутри — детали, которые не знают даже опытные импортёры. Читатель думает: «наконец-то кто-то объяснил»
— Вариант 2 «история»: начни с конкретной ситуации клиента (товар, сумма, дедлайн, ставки). Нарративная дуга: задача → нестандартное решение → результат цифрами
— Вариант 3 «деньги»: покажи цену незнания. Сколько бизнес теряет на этой проблеме в год? Потом — сколько экономит с правильным решением. Всё в рублях/долларах"""
    else:
        variant_instructions = """\
Три варианта — три разных крючка, три разных эмоции:
— Вариант 1 «парадокс»: открой с противоречием или фактом, в который трудно поверить. Читатель останавливается: «подождите, это правда?»
— Вариант 2 «боль в моменте»: опиши ситуацию, которую предприниматель переживает прямо сейчас или переживал на прошлой неделе. Максимальная конкретика сцены
— Вариант 3 «результат сразу»: первое предложение — вывод или цифра. Потом — почему это так. Читатель получает ценность с первой строки"""

    user_prompt = f"""Напиши 3 варианта поста на тему: «{topic}»

{format_prompt}

Тон:
{style_prompt}{contact_block}

{variant_instructions}

Каждый вариант — своя точка входа, свои факты, своя эмоция. Не повторяй одни и те же предложения и цифры в разных вариантах.

ПРАВИЛО CTA: в призыве к действию пиши «ваш менеджер» или «наш менеджер» — без личных имён. Если выше указан «Контакт для CTA» — ОБЯЗАТЕЛЬНО включи его (телефон, email) в конец поста.

КРИТИЧНО — в итоговом тексте каждого варианта НЕЛЬЗЯ использовать технические слова-заголовки: «Вступление», «Заголовок», «Контекст», «Блок», «CTA», «Итог», «Решение», «Подводные камни» и подобные. Эти слова — только структурная схема, подписчики их видеть не должны.

ОРФОГРАФИЯ: перед финальным ответом проверь каждое слово — ни одной опечатки, ни одной грамматической ошибки.

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
    _msgs = [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}]
    try:
        response = await client.chat.completions.create(
            model=model, messages=_msgs, temperature=temp,
            response_format={"type": "json_object"},
        )
    except Exception as _rfe:
        if any(x in str(_rfe).lower() for x in (
            "response_format", "json_object", "not support", "unsupport", "invalid_request", "400"
        )):
            logger.warning(f"json_object format unsupported by this provider — retrying without it: {_rfe}")
            response = await client.chat.completions.create(
                model=model, messages=_msgs, temperature=temp,
            )
        else:
            raise

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

    # Post-process each variant: strip leaked section labels, fix markdown bold
    for v in variants:
        if isinstance(v, dict) and v.get("text"):
            v["text"] = _clean_generated_text(v["text"])

    # Append currency rates at the very end of each variant's text
    if currency_text and variants:
        for v in variants:
            if isinstance(v, dict) and v.get("text"):
                v["text"] = v["text"].rstrip() + "\n\n" + currency_text

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
        contact_line = contact_info.strip() if contact_info.strip() else "seven-x.ru  ·  +7 967 202-55-54"
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

    page = random.randint(1, 4)
    logger.info(f"Pexels search: '{query}' page={page} for topic '{topic[:60]}'")
    headers = {"Authorization": api_key}
    search_url = (
        f"https://api.pexels.com/v1/search"
        f"?query={urllib.parse.quote(query)}&per_page=30&page={page}&orientation=square"
    )

    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(search_url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    photos = data.get("photos", [])
    if not photos:
        # fallback to page 1 if random page returned nothing
        search_url_p1 = (
            f"https://api.pexels.com/v1/search"
            f"?query={urllib.parse.quote(query)}&per_page=30&page=1&orientation=square"
        )
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.get(search_url_p1, headers=headers)
            resp.raise_for_status()
            photos = resp.json().get("photos", [])
    if not photos:
        raise ValueError(f"Pexels: no photos for '{query}'")

    photo = random.choice(photos)
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
    import asyncio
    prompt  = _build_image_prompt(topic, hook=hook)
    encoded = urllib.parse.quote(prompt)
    seed    = random.randint(1, 999_999)
    logger.info(f"Image prompt (seed={seed}): {prompt[:120]}")
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width=1024&height=1024&nologo=true&model=flux&seed={seed}"
    )

    filename = f"{uuid.uuid4()}.jpg"
    filepath = IMAGES_DIR / filename

    last_error: Exception = RuntimeError("no attempts")
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
                resp = await http.get(url)
                resp.raise_for_status()
                ct = resp.headers.get("content-type", "")
                if "image" not in ct and len(resp.content) < 20_000:
                    raise ValueError(f"Bad content-type '{ct}' size={len(resp.content)}")
                if len(resp.content) < 5000:
                    raise ValueError(f"Too-small response ({len(resp.content)} bytes)")
                filepath.write_bytes(resp.content)
            break
        except Exception as e:
            last_error = e
            logger.warning(f"Pollinations attempt {attempt + 1}/3 failed: {e}")
            if attempt < 2:
                await asyncio.sleep(5)
    else:
        # All Pollinations attempts failed — fall back to a free stock photo
        logger.warning("All Pollinations attempts failed — using Picsum fallback")
        try:
            picsum_seed = random.randint(1, 1000)
            picsum_url = f"https://picsum.photos/seed/{picsum_seed}/1024/1024"
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
                resp = await http.get(picsum_url)
                resp.raise_for_status()
                filepath.write_bytes(resp.content)
            logger.info(f"Picsum fallback OK: seed={picsum_seed}")
        except Exception as fe:
            logger.error(f"Picsum fallback also failed: {fe}")
            raise last_error

    _add_branding(filepath, post_text or topic, contact_info=contact_info, hook=hook)
    return f"/images/{filename}"
