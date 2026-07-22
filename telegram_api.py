from telethon import TelegramClient
from urllib.parse import urlparse
from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

from telethon import TelegramClient
from telethon.sessions import StringSession
from urllib.parse import urlparse
from dotenv import load_dotenv
import os

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")

client = TelegramClient(
    StringSession(STRING_SESSION),
    API_ID,
    API_HASH
)


async def start_telegram_client():
    if not client.is_connected():
        await client.connect()

        if not await client.is_user_authorized():
            raise Exception("StringSession недействительна")

        print("✅ Telethon подключен")


def format_number(value):
    if value is None:
        return "—"

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"

    if value >= 1_000:
        return f"{value / 1_000:.1f}K"

    return str(value)


async def get_telegram_stats(url: str):

    parsed = urlparse(url)

    parts = parsed.path.strip("/").split("/")

    if len(parts) != 2:
        raise Exception("Неверная ссылка")

    channel = parts[0]
    post_id = int(parts[1])

    entity = await client.get_entity(channel)

    message = await client.get_messages(
        entity,
        ids=post_id
    )

    if message is None:
        raise Exception("Пост не найден")

    # ---------- Название канала ----------

    channel_name = entity.title

    # ---------- Просмотры ----------

    views = message.views or 0

    # ---------- Репосты ----------

    shares = message.forwards or 0

    # ---------- Комментарии ----------

    comments = 0

    if message.replies:
        comments = message.replies.replies or 0

    # ---------- Реакции ----------

    reactions_total = 0

    if message.reactions:
        for reaction in message.reactions.results:
            reactions_total += reaction.count

    # ---------- ER ----------

    er = 0

    if views:
        er = round(reactions_total / views * 100, 2)

    return {
        "channel": channel_name,
        "views": views,
        "reactions": format_number(reactions_total),
        "shares": format_number(shares),
        "comments": format_number(comments),
        "er": er,
        "url": url
    }