import json
from pprint import pprint

with open("instagram_response.json", encoding="utf-8") as f:
    data = json.load(f)

media = data["data"]["xdt_api__v1__clips__user__connection_v2"]["edges"][0]["node"]["media"]

print("\nКЛЮЧИ MEDIA:\n")
pprint(sorted(media.keys()))

print("\nUSER:\n")
pprint(media.get("user"))

print("\nCAPTION:\n")
pprint(media.get("caption"))