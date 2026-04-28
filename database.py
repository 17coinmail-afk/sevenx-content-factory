import os
import json
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")
IS_PG = bool(DATABASE_URL)

DEFAULT_BRAND_VOICE = """Ты — контент-менеджер компании Seven-X, ведущего платёжного агента для ВЭД.

О компании:
• 12 лет на рынке, оборот импортных сделок более 4 млрд $
• 40+ компаний-плательщиков по всему миру с безупречной историей
• Валюты: USD, EUR, CNY (юань), AED (дирхам)
• Работа по агентской схеме и договору поставки
• Работа с санкционными товарами без российского следа
• Выкуп валютной выручки с доплатой 1–3% (рубль ставим вперёд)
• Возврат до 40% НДС из Китая рублями в РФ
• Переводы физлиц: Alipay, WeChat, наличные, крипта
• Скорость: рубли утром → платёжное поручение вечером
• Менеджер на связи 24/7
• Контакт: Артём, +7 967 202-55-54, artem@seven-x.ru

Пиши посты для Telegram-канала. Используй эмодзи уместно. Живо, без канцелярита. До 1200 символов."""


@contextmanager
def _cur():
    """Yields a cursor, auto-commits or rolls back."""
    if IS_PG:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()
    else:
        import sqlite3
        conn = sqlite3.connect("content_factory.db")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()


def _q(sql: str) -> str:
    """Convert ? placeholders to %s for PostgreSQL."""
    return sql.replace("?", "%s") if IS_PG else sql


def init_db():
    id_col = "id SERIAL PRIMARY KEY" if IS_PG else "id INTEGER PRIMARY KEY AUTOINCREMENT"

    with _cur() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS posts (
                {id_col},
                topic TEXT,
                text TEXT NOT NULL,
                image_path TEXT,
                style TEXT,
                hashtags TEXT,
                status TEXT DEFAULT 'draft',
                scheduled_at TEXT,
                published_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                message_id_1 TEXT,
                message_id_2 TEXT
            )
        """)

        cur.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
        )

        defaults = {
            "telegram_bot_token": "",
            "channel_1_id": "",
            "channel_2_id": "",
            "openai_api_key": "",
            "ai_base_url": "",
            "ai_model": "",
            "image_provider": "pollinations",
            "auto_post_enabled": "false",
            "auto_generate_enabled": "false",
            "auto_post_times": json.dumps(["10:00", "19:00"]),
            "brand_voice": DEFAULT_BRAND_VOICE,
        }

        for key, value in defaults.items():
            if IS_PG:
                cur.execute(
                    "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                    (key, value),
                )
            else:
                cur.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )


def get_settings() -> dict:
    with _cur() as cur:
        cur.execute("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in cur.fetchall()}


def update_setting(key: str, value: str):
    with _cur() as cur:
        if IS_PG:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, value),
            )
        else:
            cur.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )


def create_post(
    topic, text, image_path, style, hashtags, status, scheduled_at=None
) -> int:
    sql = _q(
        "INSERT INTO posts (topic, text, image_path, style, hashtags, status, scheduled_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    args = (topic, text, image_path, style, hashtags, status, scheduled_at)

    with _cur() as cur:
        if IS_PG:
            cur.execute(sql + " RETURNING id", args)
            return cur.fetchone()["id"]
        else:
            cur.execute(sql, args)
            return cur.lastrowid


def get_post(post_id: int) -> dict | None:
    with _cur() as cur:
        cur.execute(_q("SELECT * FROM posts WHERE id = ?"), (post_id,))
        r = cur.fetchone()
        return dict(r) if r else None


def get_posts(status: str = None) -> list[dict]:
    with _cur() as cur:
        if status:
            cur.execute(
                _q("SELECT * FROM posts WHERE status = ? ORDER BY created_at DESC"),
                (status,),
            )
        else:
            cur.execute("SELECT * FROM posts ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]


def update_post(post_id: int, **kwargs):
    if not kwargs:
        return
    set_clause = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [post_id]
    with _cur() as cur:
        cur.execute(_q(f"UPDATE posts SET {set_clause} WHERE id = ?"), values)


def delete_post(post_id: int):
    with _cur() as cur:
        cur.execute(_q("DELETE FROM posts WHERE id = ?"), (post_id,))


def get_scheduled_posts() -> list[dict]:
    with _cur() as cur:
        cur.execute(
            "SELECT * FROM posts WHERE status = 'scheduled' ORDER BY scheduled_at ASC"
        )
        return [dict(r) for r in cur.fetchall()]


def get_calendar_posts() -> list[dict]:
    with _cur() as cur:
        cur.execute(
            "SELECT * FROM posts WHERE status IN ('scheduled', 'published') "
            "ORDER BY COALESCE(scheduled_at, published_at) ASC"
        )
        return [dict(r) for r in cur.fetchall()]
