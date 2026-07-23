import json
import requests


PROFILE_URL = "https://www.instagram.com/graphql/query"
SHORTCODE_URL = "https://www.instagram.com/graphql/query"


HEADERS = {
    "accept": "*/*",
    "content-type": "application/x-www-form-urlencoded",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "x-csrftoken": "YuvV-QRvpR2Ggzgk0cTg1T",
    "x-ig-app-id": "936619743392459",
    "Cookie": "csrftoken=YuvV-QRvpR2Ggzgk0cTg1T; mid=aOia4gALAAHSq3em2E34YEIFkMCC"
}


def get_reel(shortcode):

    payload = {
        "fb_api_req_friendly_name": "PolarisPostActionLoadPostQueryQuery",
        "variables": json.dumps({
            "shortcode": shortcode
        }),
        "doc_id": "8845758582119845"
    }

    r = requests.post(
        SHORTCODE_URL,
        headers=HEADERS,
        data=payload,
        timeout=20
    )

    return r.json()