from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
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

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
last_total_reach = {}

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

    return None


def format_stats(stats: dict):

    if stats["platform"] == "Telegram":

        return (
            f"🔵 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n\n"
            f"👀 <code>{stats['views']}</code>\n"
            f"❤️ <b>{stats['reactions']}</b>\n"
            f"🔁 <b>{stats['shares']}</b>\n"
            f"💬 <b>{stats['comments']}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    if stats["platform"] == "YouTube":

        return (
            f"🔴 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n"
            f"<i>{stats['title']}</i>\n\n"
            f"👀 <code>{stats['views']}</code>\n"
            f"👍 <b>{stats['reactions']}</b>\n"
            f"💬 <b>{stats['comments']}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )
    
    if stats["platform"] == "Instagram":

        return (
            f"🟣 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n"
            f"<i>{stats['title']}</i>\n\n"
            f"👀 <code>{stats['views']}</code>\n"
            f"❤️ <b>{stats['reactions']}</b>\n"
            f"💬 <b>{stats['comments']}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )
    return "Неизвестная платформа"


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

    results = []
    total_views = 0
    views_for_copy = []

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

            else:
                continue
            if "views" in stats:
                total_views += int(stats["views"])
                views_for_copy.append(str(stats["views"]))
            results.append(
                format_stats(stats)
            )

        except Exception:

            print("\n" + "=" * 80)
            print(f"Ошибка при обработке ссылки:\n{url}\n")
            traceback.print_exc()
            print("=" * 80 + "\n")

            results.append(
                f"❌ Не удалось получить статистику\n{url}"
            )
            views_for_copy.append("N/A")

    if not results:

        await update.message.reply_text(
            "Не нашел поддерживаемых ссылок."
        )

        return

    message = "\n\n━━━━━━━━━━━━━━\n\n".join(results)

    if len(results) > 1:

        last_total_reach[user_id] = total_views

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

    await update.message.reply_text(
        message,
        parse_mode="HTML",
        disable_web_page_preview=True
)


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

print("🚀 REACHBITCH запущен")

app.run_polling(drop_pending_updates=True)