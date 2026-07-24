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

    host = parsed.netloc.lower()
    path = parsed.path.strip("/")

    # https://youtu.be/VIDEO_ID
    if host == "youtu.be":
        return path.split("/")[0]

    # https://youtube.com/*
    if "youtube.com" in host:

        # Shorts
        if path.startswith("shorts/"):
            return path.split("/")[1]

        # Live
        if path.startswith("live/"):
            return path.split("/")[1]

        # Embed
        if path.startswith("embed/"):
            return path.split("/")[1]

        # Обычные видео
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

    if not data.get("items"):
        raise Exception("Видео не найдено")

    item = data["items"][0]

    snippet = item["snippet"]
    statistics = item["statistics"]

    views = int(statistics.get("viewCount", 0))
    likes = int(statistics.get("likeCount", 0))
    comments = int(statistics.get("commentCount", 0))

    er = 0

    if views:
        er = round(
            (likes + comments) / views * 100,
            2
        )

    return {

        "platform": "YouTube",

        "channel": snippet["channelTitle"],

        "title": snippet["title"],

        "views": views,

        "views_raw": views,

        "reactions": format_number(likes),

        "shares": "—",

        "comments": format_number(comments),

        "er": er,

        "url": url

    }