from telethon import TelegramClient
import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

client = TelegramClient("reachbitch", API_ID, API_HASH)


async def main():
    entity = await client.get_entity("yandexfintech")

    message = await client.get_messages(entity, ids=110)

    print("\n========== RESULT ==========")

    print("Views:", message.views)

    print("Forwards:", message.forwards)

    print("Replies:", message.replies)

    print("Reactions:", message.reactions)

    print("============================")


with client:
    client.loop.run_until_complete(main())