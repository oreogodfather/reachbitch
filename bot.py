from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from dotenv import load_dotenv
from urllib.parse import urlparse
from upstash_redis.asyncio import Redis

import os
import re
import json
import html
import traceback
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram_api import (
    get_telegram_stats,
    start_telegram_client,
)

from youtube_api import (
    get_youtube_stats,
)

from instagram_api import (
    get_instagram_stats,
)

from tiktok_api import (
    get_tiktok_stats,
)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USERNAME = "oreogod"
ADMIN_CHAT_ID = 96168275

# user_id -> {"chat_id":, "message_id":}
pending_title = {}

# user_id -> {"chat_id":, "message_id":}
pending_budget = {}
pending_cbudget = {}
pending_update = {}

redis = Redis(
    url=os.getenv("UPSTASH_REDIS_REST_URL"),
    token=os.getenv("UPSTASH_REDIS_REST_TOKEN"),
)

MESSAGE_DATA_TTL = 60 * 60 * 24 * 30  # месяц, потом запись сама протухнет

# какое сырое поле стоит за каждой строкой в format_stats
RAW_FIELDS = {
    "views":     ("views_raw", "views"),
    "reactions": ("likes_raw", None),
    "comments":  ("comments_raw", None),
    "shares":    ("shares_raw", None),
}


async def save_message_data(message_id, urls, snapshots, title=None, base_text=None, budget=None, cbudgets=None):

    payload = json.dumps({
        "urls": urls,
        "snapshots": snapshots,
        "title": title,
        "base_text": base_text,
        "budget": budget,
        "cbudgets": cbudgets,
    })

    await redis.set(
        f"msg:{message_id}",
        payload,
        ex=MESSAGE_DATA_TTL,
    )


async def load_message_data(message_id):

    raw = await redis.get(f"msg:{message_id}")

    if not raw:
        return None

    return json.loads(raw)


async def track_user(user_id):
    """Отмечает юзера как уникального пользователя бота. Не должно ронять бота."""

    try:
        await redis.sadd("stats:users", str(user_id))
    except Exception:
        traceback.print_exc()


DAILY_COUNTER_TTL = 60 * 60 * 24 * 2  # держим счетчик дня чуть дольше суток, на всякий


async def track_check(platform, url=None):
    """Считает количество проверенных ссылок, суммарно, по платформам и за сегодня."""

    try:
        await redis.incr("stats:checks:total")
        await redis.incr(f"stats:checks:{platform}")

        today = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")

        await redis.incr(f"stats:checks:daily:{today}")
        await redis.expire(f"stats:checks:daily:{today}", DAILY_COUNTER_TTL)

        if url:
            await redis.sadd("stats:unique_urls", url)

    except Exception:
        traceback.print_exc()


async def get_counter(key):

    value = await redis.get(key)

    return int(value) if value else 0


CHAT_LOG_LIMIT = 200  # сколько последних сообщений на чат храним в логе для /clean


async def log_message(chat_id, message_id, is_stat=False):
    """
    Запоминает id сообщения в чате и признак "это пост со статистикой".
    Нужно для команды /clean. Не должно ронять бота.
    """

    try:
        key = f"chatlog:{chat_id}"
        await redis.lpush(key, json.dumps({"id": message_id, "stat": is_stat}))
        await redis.ltrim(key, 0, CHAT_LOG_LIMIT - 1)
        await redis.expire(key, MESSAGE_DATA_TTL)
    except Exception:
        traceback.print_exc()


async def reply_and_log(update, text, is_stat=False, **kwargs):
    msg = await update.message.reply_text(text, **kwargs)
    await log_message(update.effective_chat.id, msg.message_id, is_stat)
    return msg


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await log_message(update.effective_chat.id, update.message.message_id)
    await reply_and_log(
        update,
        "👋 Привет!\n\n"
        "Пришли одну или несколько ссылок на Telegram или YouTube."
    )


async def cmd_title(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await log_message(update.effective_chat.id, update.message.message_id)

    replied = update.message.reply_to_message

    if not replied or replied.from_user.id != context.bot.id:
        await reply_and_log(
            update,
            "Ответь этой командой на сообщение со статистикой, "
            "которое хочешь назвать."
        )
        return

    entry = await load_message_data(replied.message_id)

    if not entry:
        await reply_and_log(
            update,
            "Не нашел данные по этому сообщению — оно устарело."
        )
        return

    # Название сразу аргументом: /title Отчёт — https://docs.google.com/...
    if context.args:

        raw_title = " ".join(context.args).strip()

        await apply_title(
            context.bot,
            replied.chat_id,
            replied.message_id,
            entry,
            raw_title,
        )

        await reply_and_log(update, f"Готово, назвал: «{raw_title}» ✅")
        return

    pending_title[update.effective_user.id] = {
        "chat_id": replied.chat_id,
        "message_id": replied.message_id,
    }

    await reply_and_log(
        update,
        "Напиши название проекта следующим сообщением 👇\n\n"
        "💡 Пришли в ответ название проекта и ссылку на табличку с отчетом — "
        "тогда название станет гиперссылкой. Например: "
        "<code>Название проекта https://docs.google.com/...</code>",
        parse_mode="HTML",
    )


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await log_message(update.effective_chat.id, update.message.message_id)

    replied = update.message.reply_to_message

    if not replied or replied.from_user.id != context.bot.id:
        await reply_and_log(
            update,
            "Ответь этой командой на сообщение со статистикой, "
            "для которого хочешь посчитать CPV."
        )
        return

    entry = await load_message_data(replied.message_id)

    if not entry:
        await reply_and_log(
            update,
            "Не нашел данные по этому сообщению — оно устарело."
        )
        return

    # Бюджет сразу аргументом: /budget 100000
    if context.args:

        budget = parse_budget(" ".join(context.args))

        if budget is None:
            await reply_and_log(
                update,
                "Не понял бюджет, пришли просто число в рублях."
            )
            return

        await apply_budget(
            context.bot,
            replied.chat_id,
            replied.message_id,
            entry,
            budget,
        )

        await reply_and_log(update, f"Готово, посчитал CPV на бюджет {format_money(budget)} ₽ ✅")
        return

    pending_budget[update.effective_user.id] = {
        "chat_id": replied.chat_id,
        "message_id": replied.message_id,
    }

    await reply_and_log(
        update,
        "Пришли бюджет в рублях следующим сообщением 👇"
    )


async def cmd_cbudget(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await log_message(update.effective_chat.id, update.message.message_id)

    replied = update.message.reply_to_message

    if not replied or replied.from_user.id != context.bot.id:
        await reply_and_log(
            update,
            "Ответь этой командой на сообщение со статистикой, "
            "для которого хочешь посчитать CPV по каждой ссылке отдельно."
        )
        return

    entry = await load_message_data(replied.message_id)

    if not entry:
        await reply_and_log(
            update,
            "Не нашел данные по этому сообщению — оно устарело."
        )
        return

    expected = len(entry["urls"])

    # Бюджеты сразу вместе с командой: /cbudget 50000, 30000, 20000
    # (или каждый на своей строке — берем текст как есть, а не через
    # context.args, потому что Telegram схлопывает переносы строк в args)
    raw_text = update.message.text or ""
    suffix = re.sub(r"^/cbudget(@\w+)?\s*", "", raw_text, count=1, flags=re.IGNORECASE).strip()

    if suffix:

        cbudgets = parse_budget_list(suffix, expected)

        if cbudgets is None:
            await reply_and_log(
                update,
                f"Не понял бюджеты. Пришли {expected} чисел, "
                "по одному на каждую ссылку, в том же порядке, в котором отправлял ссылки "
                "(каждый с новой строки или через запятую)."
            )
            return

        await apply_cbudget(
            context.bot,
            replied.chat_id,
            replied.message_id,
            entry,
            cbudgets,
        )

        await reply_and_log(update, "Готово, посчитал CPV по каждой ссылке ✅")
        return

    pending_cbudget[update.effective_user.id] = {
        "chat_id": replied.chat_id,
        "message_id": replied.message_id,
        "expected": expected,
    }

    await reply_and_log(
        update,
        f"Пришли {expected} бюджетов через запятую следующим сообщением, "
        "по одному на каждую ссылку в том же порядке 👇"
    )


async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await log_message(update.effective_chat.id, update.message.message_id)

    replied = update.message.reply_to_message

    if not replied or replied.from_user.id != context.bot.id:
        await reply_and_log(
            update,
            "Ответь этой командой на сообщение со статистикой, "
            "в котором хочешь обновить список ссылок."
        )
        return

    entry = await load_message_data(replied.message_id)

    if not entry:
        await reply_and_log(
            update,
            "Не нашел данные по этому сообщению — оно устарело."
        )
        return

    raw_text = update.message.text or ""
    suffix = re.sub(r"^/update(@\w+)?\s*", "", raw_text, count=1, flags=re.IGNORECASE).strip()

    new_urls = extract_urls(suffix)

    if new_urls:

        cbudgets_reset = await apply_update(
            context.bot,
            replied.chat_id,
            replied.message_id,
            entry,
            new_urls,
        )

        reply = "Готово, обновил список ссылок ✅"

        if cbudgets_reset:
            reply += (
                "\n\n⚠️ Количество ссылок изменилось, /cbudget сбросился — "
                "выставь заново, если нужен."
            )

        await reply_and_log(update, reply)
        return

    pending_update[update.effective_user.id] = {
        "chat_id": replied.chat_id,
        "message_id": replied.message_id,
    }

    await reply_and_log(
        update,
        "Пришли актуальный список ссылок целиком следующим сообщением 👇\n\n"
        "Старые просто пересчитаются, новые добавятся на свои места."
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await log_message(update.effective_chat.id, update.message.message_id)

    username = (update.effective_user.username or "").lower()

    if username != ADMIN_USERNAME.lower():
        return

    users_count = await redis.scard("stats:users")
    total_checks = await get_counter("stats:checks:total")
    unique_urls = await redis.scard("stats:unique_urls")

    today = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d")
    checks_today = await get_counter(f"stats:checks:daily:{today}")

    lines = [
        f"👤 Уникальных юзеров: <b>{users_count}</b>",
        f"🔍 Всего проверок ссылок: <b>{total_checks}</b>",
        f"📅 Проверено сегодня: <b>{checks_today}</b>",
        f"🔗 Уникальных ссылок: <b>{unique_urls}</b>",
        "",
    ]

    platform_labels = {
        "telegram": ("🔵", "Telegram"),
        "youtube": ("🔴", "YouTube"),
        "instagram": ("🟣", "Instagram"),
        "tiktok": ("⚫", "TikTok"),
    }

    for platform, (emoji, label) in platform_labels.items():

        count = await get_counter(f"stats:checks:{platform}")

        lines.append(f"{emoji} {label}: <b>{count}</b>")

    await reply_and_log(
        update,
        "\n".join(lines),
        parse_mode="HTML",
    )


async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет из последних сообщений чата все, кроме постов со статистикой."""

    chat_id = update.effective_chat.id
    key = f"chatlog:{chat_id}"

    raw_entries = await redis.lrange(key, 0, 49)
    entries = [json.loads(raw) for raw in raw_entries]

    deleted = 0

    for entry in entries:

        if entry.get("stat"):
            continue

        try:
            await context.bot.delete_message(chat_id, entry["id"])
            deleted += 1
        except Exception:
            pass

    if entries:
        await redis.ltrim(key, len(entries), -1)

    try:
        await context.bot.delete_message(chat_id, update.message.message_id)
    except Exception:
        pass


def extract_urls(text: str):
    return re.findall(r"https?://[^\s]+", text)


def parse_budget(text: str):
    """
    Разбирает бюджет из текста, понимая копейки и разделители тысяч.
    "1 637 776,80" -> 1637776.8. Возвращает None, если разобрать не вышло.
    """

    # убираем всё до первой цифры — так валютный префикс вроде "p." или "р."
    # не оставляет точку, которую потом можно спутать с десятичным разделителем
    text = re.sub(r"^[^\d]+", "", text)

    cleaned = re.sub(r"[^\d.,]", "", text)

    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:

        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")

    elif "," in cleaned:

        whole, _, fraction = cleaned.rpartition(",")

        if whole and len(fraction) <= 2:
            cleaned = f"{whole}.{fraction}"
        else:
            cleaned = cleaned.replace(",", "")

    elif cleaned.count(".") > 1:
        # несколько точек — это разделители тысяч (европейский стиль), не копейки
        cleaned = cleaned.replace(".", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def format_money(value: float) -> str:

    if value == int(value):
        return f"{int(value):,}"

    return f"{value:,.2f}"


def is_bare_url_message(text: str) -> bool:
    """
    True, если сообщение — это просто ссылка (или несколько) без своего текста.
    Такое сообщение — новый запрос на статистику, а не название с гиперссылкой.
    """

    urls = extract_urls(text)

    if not urls:
        return False

    stripped = text
    for url in urls:
        stripped = stripped.replace(url, "")

    return not stripped.strip(" -—:|")


def build_title_html(raw_title: str) -> str:
    """
    Собирает готовый HTML-фрагмент названия. Если в тексте есть ссылка —
    делает из названия кликабельный гиперлинк (например, на гуглдок с отчетом).
    """

    urls = extract_urls(raw_title)

    if not urls:
        return f"<b>{html.escape(raw_title)}</b>"

    link = urls[0]
    label = raw_title.replace(link, "").strip(" -—:|")

    if not label:
        label = "Отчёт"

    return f'<b><a href="{html.escape(link)}">{html.escape(label)}</a></b>'


async def apply_title(bot, chat_id, message_id, entry, raw_title):

    title_html = build_title_html(raw_title)
    base_text = entry.get("base_text", "")

    titled_text = f"{title_html}\n\n{base_text}"

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=titled_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=REFRESH_KEYBOARD,
    )

    await save_message_data(
        message_id,
        entry["urls"],
        entry["snapshots"],
        title=title_html,
        base_text=base_text,
        budget=entry.get("budget"),
        cbudgets=entry.get("cbudgets"),
    )


async def apply_budget(bot, chat_id, message_id, entry, budget):

    title = entry.get("title")

    message, total_views, new_snapshots = await build_message(
        entry["urls"],
        entry["snapshots"],
        has_title=bool(title),
        budget=budget,
    )

    if message is None:
        return

    await save_message_data(
        message_id,
        entry["urls"],
        new_snapshots,
        title=title,
        base_text=message,
        budget=budget,
    )

    if title:
        message = f"{title}\n\n" + message

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=REFRESH_KEYBOARD,
    )


def parse_budget_list(text, expected_count):
    """
    Разбирает список бюджетов по ссылкам, в том же порядке.
    Если строк ровно столько же, сколько ссылок — каждая строка это
    один бюджет (так вставляется столбик из таблицы). Иначе делим
    по запятым, а если запятых нет — по пробелам.
    Возвращает None, если не удалось разобрать или количество не совпало.
    """

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if len(lines) > 1:
        # Много строк — это вставка из таблицы, каждая строка это один
        # бюджет. Никогда не делим такую вставку по запятой, иначе
        # разъедет числа с десятичной запятой на границе строк.
        parts = lines
    elif "," in text:
        parts = [p.strip() for p in text.split(",") if p.strip()]
    else:
        parts = [p.strip() for p in text.split() if p.strip()]

    if len(parts) != expected_count:
        return None

    budgets = []

    for part in parts:

        budget = parse_budget(part)

        if budget is None:
            return None

        budgets.append(budget)

    return budgets


async def apply_cbudget(bot, chat_id, message_id, entry, cbudgets):

    title = entry.get("title")

    message, total_views, new_snapshots = await build_message(
        entry["urls"],
        entry["snapshots"],
        has_title=bool(title),
        cbudgets=cbudgets,
    )

    if message is None:
        return

    await save_message_data(
        message_id,
        entry["urls"],
        new_snapshots,
        title=title,
        base_text=message,
        cbudgets=cbudgets,
    )

    if title:
        message = f"{title}\n\n" + message

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=REFRESH_KEYBOARD,
    )


def merge_update_urls(old_urls, new_urls):
    """
    Объединяет старый список ссылок с тем, что прислали в /update.

    Если прислали весь список целиком (старые ссылки идут первыми,
    в том же порядке) — используем его как есть, позиции сохранены.
    Если прислали только новые ссылки — добавляем их в конец,
    старые позиции тоже не трогаем.
    В обоих случаях /cbudget можно не сбрасывать.

    Возвращает (объединенный список, сохранились ли позиции старых ссылок).
    """

    if new_urls[:len(old_urls)] == old_urls:
        return new_urls, True

    if not any(url in old_urls for url in new_urls):
        return old_urls + new_urls, True

    merged = old_urls + [url for url in new_urls if url not in old_urls]
    return merged, False


async def apply_update(bot, chat_id, message_id, entry, new_urls):
    """
    Пересчитывает пост с новым списком ссылок. Старые ссылки берут
    дельту из прежних снэпшотов, новые считаются с нуля. /cbudget
    сбрасывается только если позиции старых ссылок могли съехать
    (см. merge_update_urls).
    """

    old_urls = entry["urls"]
    merged_urls, positions_preserved = merge_update_urls(old_urls, new_urls)

    title = entry.get("title")
    budget = entry.get("budget")
    cbudgets = entry.get("cbudgets")

    cbudgets_reset = False

    if cbudgets and not positions_preserved:
        cbudgets = None
        cbudgets_reset = True

    message, total_views, new_snapshots = await build_message(
        merged_urls,
        entry["snapshots"],
        has_title=bool(title),
        budget=budget,
        cbudgets=cbudgets,
    )

    if message is None:
        return cbudgets_reset

    await save_message_data(
        message_id,
        merged_urls,
        new_snapshots,
        title=title,
        base_text=message,
        budget=budget,
        cbudgets=cbudgets,
    )

    if title:
        message = f"{title}\n\n" + message

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=REFRESH_KEYBOARD,
    )

    return cbudgets_reset


def detect_platform(url: str):

    host = urlparse(url).netloc.lower()

    if host == "t.me":
        return "telegram"

    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"

    if "instagram.com" in host:
        return "instagram"

    if "tiktok.com" in host or "vt.tiktok.com" in host:
        return "tiktok"

    return None


def get_raw_value(stats, field):
    """Достает сырое числовое значение поля, если оно вообще доступно."""

    raw_key, fallback_key = RAW_FIELDS[field]

    if raw_key in stats and stats[raw_key] is not None:
        try:
            return int(stats[raw_key])
        except (TypeError, ValueError):
            return None

    if fallback_key and fallback_key in stats:
        try:
            return int(stats[fallback_key])
        except (TypeError, ValueError):
            return None

    return None


def snapshot_stats(stats):
    return {
        field: get_raw_value(stats, field)
        for field in RAW_FIELDS
    }


def fmt_delta(delta):

    if delta is None or delta == 0:
        return ""

    sign = "+" if delta > 0 else ""

    return f" ({sign}{delta:,})"


def fmt_float_delta(delta):

    if delta is None or abs(delta) < 0.005:
        return ""

    sign = "+" if delta > 0 else ""

    return f" ({sign}{delta:.2f})"


def apply_deltas(stats, previous_snapshot):
    """Добавляет в stats поля вида '<field>_delta', если есть с чем сравнить."""

    if not previous_snapshot:
        return

    for field in RAW_FIELDS:

        new_value = get_raw_value(stats, field)
        old_value = previous_snapshot.get(field)

        if new_value is None or old_value is None:
            continue

        stats[f"{field}_delta"] = new_value - old_value


def format_stats(stats: dict):

    views_d     = fmt_delta(stats.get("views_delta"))
    reactions_d = fmt_delta(stats.get("reactions_delta"))
    comments_d  = fmt_delta(stats.get("comments_delta"))
    shares_d    = fmt_delta(stats.get("shares_delta"))

    if stats["platform"] == "Telegram":

        return (
            f"🔵 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n\n"
            f"👀 <code>{stats['views']}</code>{views_d}\n"
            f"❤️ <b>{stats['reactions']}{reactions_d}</b>\n"
            f"🔁 <b>{stats['shares']}{shares_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    if stats["platform"] == "YouTube":

        return (
            f"🔴 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n"
            f"<i>{stats['title']}</i>\n\n"
            f"👀 <code>{stats['views']}</code>{views_d}\n"
            f"👍 <b>{stats['reactions']}{reactions_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    if stats["platform"] == "Instagram":

        return (
            f"🟣 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n"
            f"<i>{stats['title']}</i>\n\n"
            f"👀 <code>{stats['views']}</code>{views_d}\n"
            f"❤️ <b>{stats['reactions']}{reactions_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    if stats["platform"] == "TikTok":

        return (
            f"⚫ <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n"
            f"<i>{stats['title']}</i>\n\n"
            f"👀 <code>{stats['views']}</code>{views_d}\n"
            f"❤️ <b>{stats['reactions']}{reactions_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"🔁 <b>{stats['shares']}{shares_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    return "Неизвестная платформа"


async def build_message(urls, previous_snapshots=None, has_title=False, budget=None, cbudgets=None):
    """
    Считает статистику по ссылкам, сравнивает с previous_snapshots (если есть)
    и возвращает (текст сообщения, суммарный охват, новые снэпшоты для сохранения).
    """

    previous_snapshots = previous_snapshots or {}

    results = []
    total_views = 0
    total_views_delta = 0
    views_for_copy = []
    new_snapshots = {}
    cbudget_total = 0

    for idx, url in enumerate(urls):

        platform = detect_platform(url)

        if platform is None:
            continue

        cbudget = None

        if cbudgets and idx < len(cbudgets):
            cbudget = cbudgets[idx]

        try:

            if platform == "telegram":
                stats = await get_telegram_stats(url)

            elif platform == "youtube":
                stats = await get_youtube_stats(url)

            elif platform == "instagram":
                stats = await get_instagram_stats(url)

            elif platform == "tiktok":
                stats = await asyncio.to_thread(
                    get_tiktok_stats,
                    url,
                )

            else:
                continue

            await track_check(platform, url)

            apply_deltas(stats, previous_snapshots.get(url))
            new_snapshots[url] = snapshot_stats(stats)

            if "views_raw" in stats:
                total_views += int(stats["views_raw"])
                views_for_copy.append(str(stats["views"]))

                if stats.get("views_delta") is not None:
                    total_views_delta += stats["views_delta"]

            item_text = format_stats(stats)

            if cbudget is not None and stats.get("views_raw"):

                item_cpv = cbudget / int(stats["views_raw"])
                cbudget_total += cbudget

                item_text += (
                    f"\n💰 {format_money(cbudget)} ₽, "
                    f"<b>CPV:</b> {item_cpv:.2f} ₽"
                )

            results.append(item_text)

        except Exception as e:

            print("\n" + "=" * 80)
            print(f"Ошибка при обработке ссылки:\n{url}\n")
            traceback.print_exc()
            print("=" * 80 + "\n")

            results.append(
                f"❌ {e}\n{url}"
            )

            views_for_copy.append("N/A")

    if not results:
        return None, 0, new_snapshots

    if cbudgets and cbudget_total:
        budget = cbudget_total

    message = "\n\n━━━━━━━━━━━━━━\n\n".join(results)

    if len(results) > 1:

        message += (
            "\n\n━━━━━━━━━━━━━━\n\n"
            f"📊 <b>Общий охват</b>\n\n"
            f"👀 <code>{total_views}</code>{fmt_delta(total_views_delta)}\n\n"

            "📋 <b>Охваты для таблицы</b>\n\n"
            "<pre>"
            + "\n".join(views_for_copy)
            + "</pre>"
        )

    if budget:

        cpv = budget / total_views if total_views else 0

        previous_total_views = total_views - total_views_delta

        cpv_delta = None

        if total_views_delta and previous_total_views > 0:
            previous_cpv = budget / previous_total_views
            cpv_delta = cpv - previous_cpv

        message += (
            "\n\n"
            f"💰 <b>Общий бюджет:</b> {format_money(budget)} ₽\n"
            f"📈 <b>CPV:</b> {cpv:.2f} ₽{fmt_float_delta(cpv_delta)}"
        )

    elif len(results) > 1:
        message += (
            "\n\n📊 Посчитать CPV можно ответом на это сообщение: "
            "<code>/budget</code> + тотал кост — один бюджет на всё, "
            "<code>/cbudget</code> — бюджет по каждой публикации отдельно "
            "(кидай суммы в том же порядке, что и ссылки)"
        )

    if len(results) > 1 and not has_title:
        message += (
            "\n\n📝 Добавь название проекта ответом на это сообщение "
            "с командой <code>/title</code> + Название проекта. "
            "<i>Совет: закинь в то же сообщение линк на отчёт, и тогда "
            "название станет гиперссылкой</i>"
        )

    return message, total_views, new_snapshots


def build_refresh_keyboard(updated_at=None):

    if updated_at:

        now = datetime.now(ZoneInfo("Europe/Moscow"))

        if updated_at.date() == now.date():
            label = f"🔄 Обновлено в {updated_at.strftime('%H:%M')}"
        else:
            label = f"🔄 Обновлено {updated_at.strftime('%d.%m в %H:%M')}"

    else:
        label = "🔄 Обновить"

    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data="refresh")
    ]])


REFRESH_KEYBOARD = build_refresh_keyboard()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    urls = extract_urls(update.message.text)

    await log_message(update.effective_chat.id, update.message.message_id)

    # Пользователь прислал название после команды /title
    if user_id in pending_title:

        # Если прислали голую ссылку (без текста) — это новый запрос
        # статистики, а не название. Если ссылка идет с текстом —
        # считаем это названием с гиперссылкой.
        if is_bare_url_message(text):
            del pending_title[user_id]

        else:

            pending = pending_title.pop(user_id)

            entry = await load_message_data(pending["message_id"])

            if not entry:
                await reply_and_log(
                    update,
                    "Не нашел данные по этому сообщению — оно устарело."
                )
                return

            title = text.strip()

            await apply_title(
                context.bot,
                pending["chat_id"],
                pending["message_id"],
                entry,
                title,
            )

            await reply_and_log(update, f"Готово, назвал: «{title}» ✅")

            return

    # Пользователь прислал бюджет после команды /budget
    if user_id in pending_budget:

        # Если прислали ссылку — это новый запрос статистики, отменяем ожидание.
        if extract_urls(text):
            del pending_budget[user_id]

        else:

            pending = pending_budget.pop(user_id)

            budget = parse_budget(text)

            if budget is None:
                await reply_and_log(
                    update,
                    "Не понял бюджет, пришли просто число в рублях."
                )
                return

            entry = await load_message_data(pending["message_id"])

            if not entry:
                await reply_and_log(
                    update,
                    "Не нашел данные по этому сообщению — оно устарело."
                )
                return

            await apply_budget(
                context.bot,
                pending["chat_id"],
                pending["message_id"],
                entry,
                budget,
            )

            await reply_and_log(update, f"Готово, посчитал CPV на бюджет {format_money(budget)} ₽ ✅")

            return

    # Пользователь прислал бюджеты по ссылкам после команды /cbudget
    if user_id in pending_cbudget:

        # Если прислали ссылку — это новый запрос статистики, отменяем ожидание.
        if extract_urls(text):
            del pending_cbudget[user_id]

        else:

            pending = pending_cbudget.pop(user_id)

            cbudgets = parse_budget_list(text, pending["expected"])

            if cbudgets is None:
                await reply_and_log(
                    update,
                    f"Не понял бюджеты. Пришли {pending['expected']} чисел через запятую, "
                    "по одному на каждую ссылку, в том же порядке."
                )
                return

            entry = await load_message_data(pending["message_id"])

            if not entry:
                await reply_and_log(
                    update,
                    "Не нашел данные по этому сообщению — оно устарело."
                )
                return

            await apply_cbudget(
                context.bot,
                pending["chat_id"],
                pending["message_id"],
                entry,
                cbudgets,
            )

            await reply_and_log(update, "Готово, посчитал CPV по каждой ссылке ✅")

            return

    # Пользователь прислал новый список ссылок после команды /update
    if user_id in pending_update:

        # Если ссылок нет — это не то, что мы ждали, отменяем ожидание.
        if not urls:
            del pending_update[user_id]

        else:

            pending = pending_update.pop(user_id)

            entry = await load_message_data(pending["message_id"])

            if not entry:
                await reply_and_log(
                    update,
                    "Не нашел данные по этому сообщению — оно устарело."
                )
                return

            cbudgets_reset = await apply_update(
                context.bot,
                pending["chat_id"],
                pending["message_id"],
                entry,
                urls,
            )

            reply = "Готово, обновил список ссылок ✅"

            if cbudgets_reset:
                reply += (
                    "\n\n⚠️ Количество ссылок изменилось, /cbudget сбросился — "
                    "выставь заново, если нужен."
                )

            await reply_and_log(update, reply)

            return

    if not urls:

        await reply_and_log(
            update,
            "Не нашел ни одной ссылки 😔"
        )

        return

    await track_user(user_id)

    message, total_views, snapshots = await build_message(urls)

    if message is None:

        await reply_and_log(
            update,
            "Не нашел поддерживаемых ссылок."
        )

        return

    sent = await update.message.reply_text(
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=REFRESH_KEYBOARD,
    )

    await log_message(update.effective_chat.id, sent.message_id, is_stat=True)
    await save_message_data(sent.message_id, urls, snapshots, base_text=message)


async def handle_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    message_id = query.message.message_id

    entry = await load_message_data(message_id)

    if not entry:
        await query.answer("Ссылки устарели, пришли заново 😔", show_alert=True)
        return

    await query.answer("Обновляю…")

    title = entry.get("title")
    budget = entry.get("budget")
    cbudgets = entry.get("cbudgets")

    message, total_views, new_snapshots = await build_message(
        entry["urls"],
        entry["snapshots"],
        has_title=bool(title),
        budget=budget,
        cbudgets=cbudgets,
    )

    if message is None:
        return

    await save_message_data(
        message_id,
        entry["urls"],
        new_snapshots,
        title=title,
        base_text=message,
        budget=budget,
        cbudgets=cbudgets,
    )

    if title:
        message = f"{title}\n\n" + message

    updated_at = datetime.now(ZoneInfo("Europe/Moscow"))

    try:
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=build_refresh_keyboard(updated_at),
        )
    except Exception as e:
        # Telegram кидает ошибку, если текст не поменялся
        if "message is not modified" not in str(e):
            raise


async def post_init(app):

    try:
        await start_telegram_client()
    except Exception:
        print("\n" + "=" * 80)
        print("Ошибка запуска Telethon:\n")
        traceback.print_exc()
        print("=" * 80 + "\n")

    try:
        now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m %H:%M")
        await app.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🚀 Задеплоена новая версия бота ({now} МСК)",
        )
    except Exception:
        print("\n" + "=" * 80)
        print("Ошибка отправки уведомления о деплое:\n")
        traceback.print_exc()
        print("=" * 80 + "\n")


app = (
    ApplicationBuilder()
    .token(TOKEN)
    .post_init(post_init)
    .build()
)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("title", cmd_title))
app.add_handler(CommandHandler("budget", cmd_budget))
app.add_handler(CommandHandler("cbudget", cmd_cbudget))
app.add_handler(CommandHandler("update", cmd_update))
app.add_handler(CommandHandler("stats", cmd_stats))
app.add_handler(CommandHandler("clean", cmd_clean))

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message,
    )
)

app.add_handler(CallbackQueryHandler(handle_refresh, pattern="^refresh$"))

print("🚀 REACHBITCH запущен")

app.run_polling(drop_pending_updates=True)
