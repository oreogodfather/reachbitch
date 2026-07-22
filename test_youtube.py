import asyncio

from youtube_api import get_youtube_stats


async def main():

    stats = await get_youtube_stats(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )

    print(stats)


asyncio.run(main())