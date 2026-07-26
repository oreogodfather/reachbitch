import asyncio
import json
import subprocess


def _format_number(value: int):

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0", "")

    if value >= 1_000:
        return f"{value / 1_000:.1f}K".replace(".0", "")

    return str(value)


def calculate_er(views, likes, comments):

    if not views:
        return 0

    return round((likes + comments) / views * 100, 2)


def _fetch_instagram_stats(url: str):

    command = [
        "yt-dlp",
        "--print-json",
        "--no-warnings",
        "--no-playlist",
        url,
    ]

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )

    except FileNotFoundError:
        raise Exception("На сервере не установлен yt-dlp.")

    except subprocess.TimeoutExpired:
        raise Exception("Instagram слишком долго отвечает.")

    except subprocess.CalledProcessError as e:

        error = (e.stderr or e.stdout or "").lower()

        if "login required" in error or "you need to log in" in error:
            raise Exception(
                "Instagram запросил авторизацию для этого поста."
            )

        if "private" in error:
            raise Exception(
                "Пост является приватным."
            )

        if "not available" in error or "unavailable" in error:
            raise Exception(
                "Пост недоступен."
            )

        raise Exception(
            "Не удалось получить данные Instagram."
        )

    if not result.stdout.strip():
        raise Exception("Instagram не вернул данные.")

    try:
        data = json.loads(result.stdout)

    except json.JSONDecodeError:
        raise Exception("Некорректный ответ Instagram.")

    if not isinstance(data, dict):
        raise Exception("Некорректный ответ Instagram.")

    views = int(
        data.get("view_count")
        or data.get("play_count")
        or 0
    )

    likes = int(data.get("like_count") or 0)
    comments = int(data.get("comment_count") or 0)

    er = calculate_er(views, likes, comments)

    channel = (
        data.get("uploader")
        or data.get("channel")
        or data.get("uploader_id")
        or ""
    )

    title = (
        data.get("description")
        or data.get("title")
        or ""
    )

    return {

        "platform": "Instagram",

        "channel": channel,

        "title": title[:120] if title else "Instagram Reel",

        "views": views,

        "reactions": _format_number(likes),

        "comments": _format_number(comments),

        "shares": "—",

        "er": er,

        "url": data.get("webpage_url") or url,

        "views_raw": views,

        "likes_raw": likes,

        "comments_raw": comments,

        "shortcode": data.get("id"),
    }


async def get_instagram_stats(url: str):
    return await asyncio.to_thread(_fetch_instagram_stats, url)


if __name__ == "__main__":

    print(
        asyncio.run(
            get_instagram_stats(
                "https://www.instagram.com/reels/DavNwBcg1To/"
            )
        )
    )
