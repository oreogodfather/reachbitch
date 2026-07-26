import json
import re
import threading

import requests
from urllib.parse import quote


GRAPHQL_URL = "https://www.instagram.com/graphql/query"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

PROFILE_DOC_ID = "27234427476213202"
SHORTCODE_DOC_ID = "24368985919464652"

_session_lock = threading.Lock()
_session = None


def _create_guest_session():
    """
    Анонимный заход на instagram.com без логина — забираем гостевые
    куки (csrftoken и т.п.), их достаточно для публичных GraphQL-запросов.
    Не привязано ни к какому личному аккаунту, поэтому банить нечего.
    """

    session = requests.Session()

    session.headers.update({
        "user-agent": USER_AGENT,
        "accept": "*/*",
    })

    response = session.get("https://www.instagram.com/", timeout=20)
    response.raise_for_status()

    csrftoken = session.cookies.get("csrftoken")

    if not csrftoken:
        raise Exception("Не удалось получить гостевой csrftoken от Instagram")

    session.headers.update({
        "content-type": "application/x-www-form-urlencoded",
        "x-csrftoken": csrftoken,
        "x-ig-app-id": "936619743392459",
    })

    return session


def _get_session(force_new=False):

    global _session

    with _session_lock:

        if _session is None or force_new:
            _session = _create_guest_session()

        return _session


def _graphql_post(payload):

    session = _get_session()

    response = session.post(GRAPHQL_URL, data=payload, timeout=20)

    if response.status_code in (401, 403):
        # гостевая сессия протухла — берем новую и пробуем еще раз
        session = _get_session(force_new=True)
        response = session.post(GRAPHQL_URL, data=payload, timeout=20)

    response.raise_for_status()

    return response.json()


def format_number(value):

    if value is None:
        return "—"

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"

    if value >= 1_000:
        return f"{value / 1_000:.1f}K"

    return str(value)


def extract_shortcode(url):

    url = url.split("?")[0]

    match = re.search(
        r"instagram\.com/(?:[^/]+/)?(?:reels?|p)/([^/?]+)",
        url
    )

    if not match:
        raise Exception("Invalid instagram url")

    return match.group(1)


def create_shortcode_payload(shortcode):

    variables = json.dumps({
        "shortcode": shortcode
    })

    encoded = quote(variables)

    return (
        "av=0"
        "&__d=www"
        "&__user=0"
        "&__a=1"
        "&__req=u"
        "&dpr=1"
        "&fb_api_caller_class=RelayModern"
        "&fb_api_req_friendly_name=PolarisPostRootQuery"
        "&server_timestamps=true"
        f"&variables={encoded}"
        f"&doc_id={SHORTCODE_DOC_ID}"
    )


def get_shortcode_info(shortcode):

    payload = create_shortcode_payload(shortcode)

    return _graphql_post(payload)


def get_profile_reels(user_id):

    payload = {
        "fb_api_req_friendly_name":
        "PolarisProfileReelsTabContentQuery",

        "doc_id": PROFILE_DOC_ID,

        "variables": json.dumps({
            "data": {
                "include_feed_video": True,
                "page_size": 100,
                "target_user_id": str(user_id)
            }
        })
    }

    return _graphql_post(payload)

def find_media_by_shortcode(edges, shortcode):

    for edge in edges:

        media = edge["node"]["media"]

        if media["code"] == shortcode:
            return media

    return None


def calculate_er(views, likes, comments):

    if not views:
        return 0

    return round((likes + comments) / views * 100, 2)


async def get_instagram_stats(url):

    shortcode = extract_shortcode(url)

    #
    # Первый GraphQL
    #

    reel = get_shortcode_info(shortcode)

    item = (
        reel["data"]
        ["xdt_api__v1__media__shortcode__web_info"]
        ["items"][0]
    )

    owner = item["user"]

    owner_id = owner["pk"]

    username = owner["username"]

    caption = ""

    if item.get("caption"):
        caption = item["caption"].get("text", "")

    likes = item.get("like_count", 0)

    comments = item.get("comment_count", 0)

    #
    # Второй GraphQL
    #

    profile = get_profile_reels(owner_id)

    edges = (
        profile["data"]
        ["xdt_api__v1__clips__user__connection_v2"]
        ["edges"]
    )

    media = find_media_by_shortcode(edges, shortcode)

    if not media:
        raise Exception("Reel not found in profile")

    views = media.get("play_count", 0)

    return {
        "platform": "Instagram",
        "channel": username,
        "title": caption[:120] if caption else "Instagram Reel",
        "views": views,
        "reactions": format_number(likes),
        "comments": format_number(comments),
        "shares": "—",
        "er": calculate_er(views, likes, comments),
        "url": url,

        #
        # пригодится потом
        #

        "views_raw": views,
        "likes_raw": likes,
        "comments_raw": comments,
        "owner_id": owner_id,
        "shortcode": shortcode,
    }
