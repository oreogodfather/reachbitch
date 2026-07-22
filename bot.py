from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from dotenv import load_dotenv
import os
import re

from telegram_api import (
    get_telegram_stats,
    start_telegram_client,
)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "Пришли одну или несколько ссылок на посты Telegram."
    )


def extract_urls(text: str):
    """
    Возвращает все ссылки из сообщения.
    """

    return re.findall(r"https?://[^\s]+", text)


def format_stats(stats: dict):

    return (
        f"🔵 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n\n"
        f"👀 <code>{stats['views']}</code>\n"
        f"❤️ <b>{stats['reactions']}</b>\n"
        f"🔁 <b>{stats['shares']}</b>\n"
        f"💬 <b>{stats['comments']}</b>\n"
        f"📈 <b>{stats['er']}%</b>"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    urls = extract_urls(update.message.text)

    if not urls:

        await update.message.reply_text(
            "Не нашел ни одной ссылки 😔"
        )

        return

    results = []

    for url in urls:

        if "t.me/" not in url:
            continue

        try:

            stats = await get_telegram_stats(url)

            results.append(
                format_stats(stats)
            )

        except Exception as e:

            print(e)

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

    await start_telegram_client()


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

app.run_polling()