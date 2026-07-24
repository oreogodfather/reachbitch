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
        "--no-call-home",
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
        raise Exception("yt-dlp is not installed.")

    except subprocess.TimeoutExpired:
        raise Exception("yt-dlp timed out after 15 seconds.")

    except subprocess.CalledProcessError as e:

        raise Exception(
            f"""
yt-dlp exited with code {e.returncode}

STDOUT:
{e.stdout}

STDERR:
{e.stderr}
"""
        )

    if not result.stdout.strip():
        raise Exception("yt-dlp returned empty output.")

    try:
        data = json.loads(result.stdout)

    except json.JSONDecodeError:

        raise Exception(
            f"""
yt-dlp returned invalid JSON.

STDOUT:
{result.stdout}

STDERR:
{result.stderr}
"""
        )

    if not isinstance(data, dict):
        raise Exception("yt-dlp returned unexpected response.")

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

        "views": _format_number(views),

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