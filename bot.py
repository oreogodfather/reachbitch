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

import os
import re
import traceback
import asyncio

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
last_total_reach = {}

# message_id -> {"urls": [...], "snapshots": {url: {"views": int, "reactions": int, "comments": int, "shares": int}}}
message_data = {}

# какое сырое поле стоит за каждой строкой в format_stats
RAW_FIELDS = {
    "views":     ("views_raw", "views"),
    "reactions": ("likes_raw", None),
    "comments":  ("comments_raw", None),
    "shares":    ("shares_raw", None),
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Пришли одну или несколько ссылок на Telegram или YouTube."
    )


def extract_urls(text: str):
    return re.findall(r"https?://[^\s]+", text)


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
            f"👀 <code>{stats['views']}{views_d}</code>\n"
            f"❤️ <b>{stats['reactions']}{reactions_d}</b>\n"
            f"🔁 <b>{stats['shares']}{shares_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    if stats["platform"] == "YouTube":

        return (
            f"🔴 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n"
            f"<i>{stats['title']}</i>\n\n"
            f"👀 <code>{stats['views']}{views_d}</code>\n"
            f"👍 <b>{stats['reactions']}{reactions_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    if stats["platform"] == "Instagram":

        return (
            f"🟣 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n"
            f"<i>{stats['title']}</i>\n\n"
            f"👀 <code>{stats['views']}{views_d}</code>\n"
            f"❤️ <b>{stats['reactions']}{reactions_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    if stats["platform"] == "TikTok":

        return (
            f"⚫ <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n"
            f"<i>{stats['title']}</i>\n\n"
            f"👀 <code>{stats['views']}{views_d}</code>\n"
            f"❤️ <b>{stats['reactions']}{reactions_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"🔁 <b>{stats['shares']}{shares_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    return "Неизвестная платформа"


async def build_message(urls, previous_snapshots=None):
    """
    Считает статистику по ссылкам, сравнивает с previous_snapshots (если есть)
    и возвращает (текст сообщения, суммарный охват, новые снэпшоты для сохранения).
    """

    previous_snapshots = previous_snapshots or {}

    results = []
    total_views = 0
    views_for_copy = []
    new_snapshots = {}

    for url in urls:

        platform = detect_platform(url)

        if platform is None:
            continue

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

            apply_deltas(stats, previous_snapshots.get(url))
            new_snapshots[url] = snapshot_stats(stats)

            if "views_raw" in stats:
                total_views += int(stats["views_raw"])
                views_for_copy.append(str(stats["views"]))

            results.append(
                format_stats(stats)
            )

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

    message = "\n\n━━━━━━━━━━━━━━\n\n".join(results)

    if len(results) > 1:

        message += (
            "\n\n━━━━━━━━━━━━━━\n\n"
            f"📊 <b>Общий охват</b>\n\n"
            f"👀 <code>{total_views}</code>\n\n"

            "📋 <b>Охваты для таблицы</b>\n\n"
            "<pre>"
            + "\n".join(views_for_copy)
            + "</pre>\n\n"

            "💡 Пришлите следующим сообщением бюджет в ₽ — посчитаю общий CPV."
        )

    return message, total_views, new_snapshots


REFRESH_KEYBOARD = InlineKeyboardMarkup([[
    InlineKeyboardButton("🔄 Обновить", callback_data="refresh")
]])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    urls = extract_urls(update.message.text)
    # Пользователь прислал бюджет после подсчета общего охвата

    if user_id in last_total_reach:

        # Если пользователь прислал новую ссылку —
        # начинаем новый расчет, а не считаем это бюджетом.
        if extract_urls(text):
            del last_total_reach[user_id]

        else:

            budget = re.sub(r"[^\d]", "", text)

            if budget.isdigit():

                budget = int(budget)

                views = last_total_reach[user_id]

                cpv = budget / views

                await update.message.reply_text(

                    f"💰 Бюджет: <b>{budget:,} ₽</b>\n"
                    f"👀 Охват: <b>{views:,}</b>\n"
                    f"📈 CPV: <b>{cpv:.4f} ₽</b>",

                    parse_mode="HTML"

                )

                del last_total_reach[user_id]

                return
    if not urls:

        await update.message.reply_text(
            "Не нашел ни одной ссылки 😔"
        )

        return

    message, total_views, snapshots = await build_message(urls)

    if message is None:

        await update.message.reply_text(
            "Не нашел поддерживаемых ссылок."
        )

        return

    if total_views:
        last_total_reach[user_id] = total_views

    sent = await update.message.reply_text(
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=REFRESH_KEYBOARD,
    )

    message_data[sent.message_id] = {
        "urls": urls,
        "snapshots": snapshots,
    }


async def handle_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    message_id = query.message.message_id

    entry = message_data.get(message_id)

    if not entry:
        await query.answer("Ссылки устарели, пришли заново 😔", show_alert=True)
        return

    await query.answer("Обновляю…")

    message, total_views, new_snapshots = await build_message(
        entry["urls"],
        entry["snapshots"],
    )

    if message is None:
        return

    user_id = update.effective_user.id

    if total_views:
        last_total_reach[user_id] = total_views

    message_data[message_id] = {
        "urls": entry["urls"],
        "snapshots": new_snapshots,
    }

    try:
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=REFRESH_KEYBOARD,
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


app = (
    ApplicationBuilder()
    .token(TOKEN)
    .post_init(post_init)
    .build()
)

app.add_handler(CommandHandler("start", start))

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message,
    )
)

app.add_handler(CallbackQueryHandler(handle_refresh, pattern="^refresh$"))

print("🚀 REACHBITCH запущен")

app.run_polling(drop_pending_updates=True)
