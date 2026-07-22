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

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")


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

    return "Неизвестная платформа"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    urls = extract_urls(update.message.text)

    if not urls:

        await update.message.reply_text(
            "Не нашел ни одной ссылки 😔"
        )

        return

    results = []

    for url in urls:

        platform = detect_platform(url)

        if platform is None:
            continue

        try:

            if platform == "telegram":
                stats = await get_telegram_stats(url)

            elif platform == "youtube":
                stats = await get_youtube_stats(url)

            else:
                continue

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

    if not results:

        await update.message.reply_text(
            "Не нашел поддерживаемых ссылок."
        )

        return

    message = "\n\n━━━━━━━━━━━━━━\n\n".join(results)

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