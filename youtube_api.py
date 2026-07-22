import os
import requests

from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("YOUTUBE_API_KEY")


def format_number(value):

    if value is None:
        return "—"

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"

    if value >= 1_000:
        return f"{value / 1_000:.1f}K"

    return str(value)


def extract_video_id(url: str):

    parsed = urlparse(url)

    if parsed.netloc == "youtu.be":
        return parsed.path.strip("/")

    if "youtube.com" in parsed.netloc:
        query = parse_qs(parsed.query)

        if "v" in query:
            return query["v"][0]

    raise Exception("Не удалось определить ID видео")


async def get_youtube_stats(url: str):

    video_id = extract_video_id(url)

    response = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={
            "id": video_id,
            "part": "snippet,statistics",
            "key": API_KEY
        }
    )

    data = response.json()

    if not data["items"]:
        raise Exception("Видео не найдено")

    item = data["items"][0]

    snippet = item["snippet"]
    statistics = item["statistics"]

    views = int(statistics.get("viewCount", 0))
    likes = int(statistics.get("likeCount", 0))
    comments = int(statistics.get("commentCount", 0))

    er = 0

    if views > 0:
        er = round(
            (likes + comments) / views * 100,
            2
        )

    return {

        "platform": "YouTube",

        "channel": snippet["channelTitle"],

        "title": snippet["title"],

        "views": views,

        "reactions": format_number(likes),

        "shares": "—",

        "comments": format_number(comments),

        "er": er,

        "url": url

    }