import json
import subprocess


def _format_number(value: int):

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0", "")

    if value >= 1_000:
        return f"{value / 1_000:.1f}K".replace(".0", "")

    return str(value)


def get_tiktok_stats(url: str):

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
            timeout=15,
            check=True,
        )

    except FileNotFoundError:
        raise Exception("На сервере не установлен yt-dlp.")

    except subprocess.TimeoutExpired:
        raise Exception("TikTok слишком долго отвечает.")

    except subprocess.CalledProcessError as e:

        error = (e.stderr or e.stdout or "").lower()

        if "your ip address is blocked" in error:
            raise Exception(
                "TikTok ограничил доступ к этому видео с IP сервера."
            )

        if "private" in error:
            raise Exception(
                "Видео является приватным."
            )

        if "video unavailable" in error:
            raise Exception(
                "Видео недоступно."
            )

        if "not available" in error:
            raise Exception(
                "Видео недоступно."
            )

        raise Exception(
            "Не удалось получить данные TikTok."
        )

    if not result.stdout.strip():
        raise Exception("TikTok не вернул данные.")

    try:
        data = json.loads(result.stdout)

    except json.JSONDecodeError:
        raise Exception("Некорректный ответ TikTok.")

    if not isinstance(data, dict):
        raise Exception("Некорректный ответ TikTok.")

    views = int(data.get("view_count") or 0)
    likes = int(data.get("like_count") or 0)
    comments = int(data.get("comment_count") or 0)

    shares = int(
        data.get("repost_count")
        or data.get("share_count")
        or 0
    )

    er = 0

    if views:
        er = round(
            (likes + comments + shares)
            / views
            * 100,
            2,
        )

    channel = (
        data.get("uploader")
        or data.get("channel")
        or data.get("creator")
        or ""
    )

    title = (
        data.get("title")
        or data.get("fulltitle")
        or data.get("description")
        or ""
    )

    return {

        "platform": "TikTok",

        "channel": channel,

        "title": title,

        "views": str(views),

        "reactions": _format_number(likes),

        "comments": _format_number(comments),

        "shares": _format_number(shares),

        "er": er,

        "url": data.get("webpage_url") or url,

        "views_raw": views,

        "likes_raw": likes,

        "comments_raw": comments,

        "shares_raw": shares,

        "video_id": data.get("id"),
    }


if __name__ == "__main__":

    print(
        get_tiktok_stats(
            "https://vt.tiktok.com/ZSXCWjwMJ/"
        )
    )