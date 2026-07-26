from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from dotenv import load_dotenv
from urllib.parse import urlparse
from upstash_redis.asyncio import Redis

import os
import re
import json
import html
import traceback
import asyncio

from telegram_api import (
    get_telegram_stats,
    start_telegram_client,
)

from youtube_api import (
    get_youtube_stats,
)

from instagram_api import (
    get_instagram_stats,
)

from tiktok_api import (
    get_tiktok_stats,
)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USERNAME = "oreogod"

# user_id -> {"chat_id":, "message_id":}
pending_title = {}

# user_id -> {"chat_id":, "message_id":}
pending_budget = {}

redis = Redis(
    url=os.getenv("UPSTASH_REDIS_REST_URL"),
    token=os.getenv("UPSTASH_REDIS_REST_TOKEN"),
)

MESSAGE_DATA_TTL = 60 * 60 * 24 * 30  # месяц, потом запись сама протухнет

# какое сырое поле стоит за каждой строкой в format_stats
RAW_FIELDS = {
    "views":     ("views_raw", "views"),
    "reactions": ("likes_raw", None),
    "comments":  ("comments_raw", None),
    "shares":    ("shares_raw", None),
}


async def save_message_data(message_id, urls, snapshots, title=None, base_text=None, budget=None):

    payload = json.dumps({
        "urls": urls,
        "snapshots": snapshots,
        "title": title,
        "base_text": base_text,
        "budget": budget,
    })

    await redis.set(
        f"msg:{message_id}",
        payload,
        ex=MESSAGE_DATA_TTL,
    )


async def load_message_data(message_id):

    raw = await redis.get(f"msg:{message_id}")

    if not raw:
        return None

    return json.loads(raw)


async def track_user(user_id):
    """Отмечает юзера как уникального пользователя бота. Не должно ронять бота."""

    try:
        await redis.sadd("stats:users", str(user_id))
    except Exception:
        traceback.print_exc()


async def track_check(platform):
    """Считает количество проверенных ссылок, суммарно и по платформам."""

    try:
        await redis.incr("stats:checks:total")
        await redis.incr(f"stats:checks:{platform}")
    except Exception:
        traceback.print_exc()


async def get_counter(key):

    value = await redis.get(key)

    return int(value) if value else 0


CHAT_LOG_LIMIT = 200  # сколько последних сообщений на чат храним в логе для /clean


async def log_message(chat_id, message_id, is_stat=False):
    """
    Запоминает id сообщения в чате и признак "это пост со статистикой".
    Нужно для команды /clean. Не должно ронять бота.
    """

    try:
        key = f"chatlog:{chat_id}"
        await redis.lpush(key, json.dumps({"id": message_id, "stat": is_stat}))
        await redis.ltrim(key, 0, CHAT_LOG_LIMIT - 1)
        await redis.expire(key, MESSAGE_DATA_TTL)
    except Exception:
        traceback.print_exc()


async def reply_and_log(update, text, is_stat=False, **kwargs):
    msg = await update.message.reply_text(text, **kwargs)
    await log_message(update.effective_chat.id, msg.message_id, is_stat)
    return msg


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await log_message(update.effective_chat.id, update.message.message_id)
    await reply_and_log(
        update,
        "👋 Привет!\n\n"
        "Пришли одну или несколько ссылок на Telegram или YouTube."
    )


async def cmd_title(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await log_message(update.effective_chat.id, update.message.message_id)

    replied = update.message.reply_to_message

    if not replied or replied.from_user.id != context.bot.id:
        await reply_and_log(
            update,
            "Ответь этой командой на сообщение со статистикой, "
            "которое хочешь назвать."
        )
        return

    entry = await load_message_data(replied.message_id)

    if not entry:
        await reply_and_log(
            update,
            "Не нашел данные по этому сообщению — оно устарело."
        )
        return

    # Название сразу аргументом: /title Отчёт — https://docs.google.com/...
    if context.args:

        raw_title = " ".join(context.args).strip()

        await apply_title(
            context.bot,
            replied.chat_id,
            replied.message_id,
            entry,
            raw_title,
        )

        await reply_and_log(update, f"Готово, назвал: «{raw_title}» ✅")
        return

    pending_title[update.effective_user.id] = {
        "chat_id": replied.chat_id,
        "message_id": replied.message_id,
    }

    await reply_and_log(
        update,
        "Напиши название проекта следующим сообщением 👇\n\n"
        "💡 Пришли в ответ название проекта и ссылку на табличку с отчетом — "
        "тогда название станет гиперссылкой. Например: "
        "<code>Название проекта https://docs.google.com/...</code>",
        parse_mode="HTML",
    )


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await log_message(update.effective_chat.id, update.message.message_id)

    replied = update.message.reply_to_message

    if not replied or replied.from_user.id != context.bot.id:
        await reply_and_log(
            update,
            "Ответь этой командой на сообщение со статистикой, "
            "для которого хочешь посчитать CPV."
        )
        return

    entry = await load_message_data(replied.message_id)

    if not entry:
        await reply_and_log(
            update,
            "Не нашел данные по этому сообщению — оно устарело."
        )
        return

    # Бюджет сразу аргументом: /budget 100000
    if context.args:

        budget = parse_budget(" ".join(context.args))

        if budget is None:
            await reply_and_log(
                update,
                "Не понял бюджет, пришли просто число в рублях."
            )
            return

        await apply_budget(
            context.bot,
            replied.chat_id,
            replied.message_id,
            entry,
            budget,
        )

        await reply_and_log(update, f"Готово, посчитал CPV на бюджет {format_money(budget)} ₽ ✅")
        return

    pending_budget[update.effective_user.id] = {
        "chat_id": replied.chat_id,
        "message_id": replied.message_id,
    }

    await reply_and_log(
        update,
        "Пришли бюджет в рублях следующим сообщением 👇"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await log_message(update.effective_chat.id, update.message.message_id)

    username = (update.effective_user.username or "").lower()

    if username != ADMIN_USERNAME.lower():
        return

    users_count = await redis.scard("stats:users")
    total_checks = await get_counter("stats:checks:total")

    lines = [
        f"👤 Уникальных юзеров: <b>{users_count}</b>",
        f"🔍 Всего проверок ссылок: <b>{total_checks}</b>",
        "",
    ]

    platform_labels = {
        "telegram": ("🔵", "Telegram"),
        "youtube": ("🔴", "YouTube"),
        "instagram": ("🟣", "Instagram"),
        "tiktok": ("⚫", "TikTok"),
    }

    for platform, (emoji, label) in platform_labels.items():

        count = await get_counter(f"stats:checks:{platform}")

        lines.append(f"{emoji} {label}: <b>{count}</b>")

    await reply_and_log(
        update,
        "\n".join(lines),
        parse_mode="HTML",
    )


async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет из последних сообщений чата все, кроме постов со статистикой."""

    chat_id = update.effective_chat.id
    key = f"chatlog:{chat_id}"

    raw_entries = await redis.lrange(key, 0, 49)
    entries = [json.loads(raw) for raw in raw_entries]

    deleted = 0

    for entry in entries:

        if entry.get("stat"):
            continue

        try:
            await context.bot.delete_message(chat_id, entry["id"])
            deleted += 1
        except Exception:
            pass

    if entries:
        await redis.ltrim(key, len(entries), -1)

    try:
        await context.bot.delete_message(chat_id, update.message.message_id)
    except Exception:
        pass


def extract_urls(text: str):
    return re.findall(r"https?://[^\s]+", text)


def parse_budget(text: str):
    """
    Разбирает бюджет из текста, понимая копейки и разделители тысяч.
    "1 637 776,80" -> 1637776.8. Возвращает None, если разобрать не вышло.
    """

    cleaned = re.sub(r"[^\d.,]", "", text)

    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:

        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")

    elif "," in cleaned:

        whole, _, fraction = cleaned.rpartition(",")

        if whole and len(fraction) <= 2:
            cleaned = f"{whole}.{fraction}"
        else:
            cleaned = cleaned.replace(",", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def format_money(value: float) -> str:

    if value == int(value):
        return f"{int(value):,}"

    return f"{value:,.2f}"


def is_bare_url_message(text: str) -> bool:
    """
    True, если сообщение — это просто ссылка (или несколько) без своего текста.
    Такое сообщение — новый запрос на статистику, а не название с гиперссылкой.
    """

    urls = extract_urls(text)

    if not urls:
        return False

    stripped = text
    for url in urls:
        stripped = stripped.replace(url, "")

    return not stripped.strip(" -—:|")


def build_title_html(raw_title: str) -> str:
    """
    Собирает готовый HTML-фрагмент названия. Если в тексте есть ссылка —
    делает из названия кликабельный гиперлинк (например, на гуглдок с отчетом).
    """

    urls = extract_urls(raw_title)

    if not urls:
        return f"<b>{html.escape(raw_title)}</b>"

    link = urls[0]
    label = raw_title.replace(link, "").strip(" -—:|")

    if not label:
        label = "Отчёт"

    return f'<b><a href="{html.escape(link)}">{html.escape(label)}</a></b>'


async def apply_title(bot, chat_id, message_id, entry, raw_title):

    title_html = build_title_html(raw_title)
    base_text = entry.get("base_text", "")

    titled_text = f"{title_html}\n\n{base_text}"

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=titled_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=REFRESH_KEYBOARD,
    )

    await save_message_data(
        message_id,
        entry["urls"],
        entry["snapshots"],
        title=title_html,
        base_text=base_text,
        budget=entry.get("budget"),
    )


async def apply_budget(bot, chat_id, message_id, entry, budget):

    title = entry.get("title")

    message, total_views, new_snapshots = await build_message(
        entry["urls"],
        entry["snapshots"],
        has_title=bool(title),
        budget=budget,
    )

    if message is None:
        return

    await save_message_data(
        message_id,
        entry["urls"],
        new_snapshots,
        title=title,
        base_text=message,
        budget=budget,
    )

    if title:
        message = f"{title}\n\n" + message

    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=REFRESH_KEYBOARD,
    )


def detect_platform(url: str):

    host = urlparse(url).netloc.lower()

    if host == "t.me":
        return "telegram"

    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"

    if "instagram.com" in host:
        return "instagram"

    if "tiktok.com" in host or "vt.tiktok.com" in host:
        return "tiktok"

    return None


def get_raw_value(stats, field):
    """Достает сырое числовое значение поля, если оно вообще доступно."""

    raw_key, fallback_key = RAW_FIELDS[field]

    if raw_key in stats and stats[raw_key] is not None:
        try:
            return int(stats[raw_key])
        except (TypeError, ValueError):
            return None

    if fallback_key and fallback_key in stats:
        try:
            return int(stats[fallback_key])
        except (TypeError, ValueError):
            return None

    return None


def snapshot_stats(stats):
    return {
        field: get_raw_value(stats, field)
        for field in RAW_FIELDS
    }


def fmt_delta(delta):

    if delta is None or delta == 0:
        return ""

    sign = "+" if delta > 0 else ""

    return f" ({sign}{delta:,})"


def fmt_float_delta(delta):

    if delta is None or abs(delta) < 0.0001:
        return ""

    sign = "+" if delta > 0 else ""

    return f" ({sign}{delta:.4f})"


def apply_deltas(stats, previous_snapshot):
    """Добавляет в stats поля вида '<field>_delta', если есть с чем сравнить."""

    if not previous_snapshot:
        return

    for field in RAW_FIELDS:

        new_value = get_raw_value(stats, field)
        old_value = previous_snapshot.get(field)

        if new_value is None or old_value is None:
            continue

        stats[f"{field}_delta"] = new_value - old_value


def format_stats(stats: dict):

    views_d     = fmt_delta(stats.get("views_delta"))
    reactions_d = fmt_delta(stats.get("reactions_delta"))
    comments_d  = fmt_delta(stats.get("comments_delta"))
    shares_d    = fmt_delta(stats.get("shares_delta"))

    if stats["platform"] == "Telegram":

        return (
            f"🔵 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n\n"
            f"👀 <code>{stats['views']}</code>{views_d}\n"
            f"❤️ <b>{stats['reactions']}{reactions_d}</b>\n"
            f"🔁 <b>{stats['shares']}{shares_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    if stats["platform"] == "YouTube":

        return (
            f"🔴 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n"
            f"<i>{stats['title']}</i>\n\n"
            f"👀 <code>{stats['views']}</code>{views_d}\n"
            f"👍 <b>{stats['reactions']}{reactions_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    if stats["platform"] == "Instagram":

        return (
            f"🟣 <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n"
            f"<i>{stats['title']}</i>\n\n"
            f"👀 <code>{stats['views']}</code>{views_d}\n"
            f"❤️ <b>{stats['reactions']}{reactions_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    if stats["platform"] == "TikTok":

        return (
            f"⚫ <a href='{stats['url']}'><b>{stats['channel']}</b></a>\n"
            f"<i>{stats['title']}</i>\n\n"
            f"👀 <code>{stats['views']}</code>{views_d}\n"
            f"❤️ <b>{stats['reactions']}{reactions_d}</b>\n"
            f"💬 <b>{stats['comments']}{comments_d}</b>\n"
            f"🔁 <b>{stats['shares']}{shares_d}</b>\n"
            f"📈 <b>{stats['er']}%</b>"
        )

    return "Неизвестная платформа"


async def build_message(urls, previous_snapshots=None, has_title=False, budget=None):
    """
    Считает статистику по ссылкам, сравнивает с previous_snapshots (если есть)
    и возвращает (текст сообщения, суммарный охват, новые снэпшоты для сохранения).
    """

    previous_snapshots = previous_snapshots or {}

    results = []
    total_views = 0
    total_views_delta = 0
    views_for_copy = []
    new_snapshots = {}

    for url in urls:

        platform = detect_platform(url)

        if platform is None:
            continue

        try:

            if platform == "telegram":
                stats = await get_telegram_stats(url)

            elif platform == "youtube":
                stats = await get_youtube_stats(url)

            elif platform == "instagram":
                stats = await get_instagram_stats(url)

            elif platform == "tiktok":
                stats = await asyncio.to_thread(
                    get_tiktok_stats,
                    url,
                )

            else:
                continue

            await track_check(platform)

            apply_deltas(stats, previous_snapshots.get(url))
            new_snapshots[url] = snapshot_stats(stats)

            if "views_raw" in stats:
                total_views += int(stats["views_raw"])
                views_for_copy.append(str(stats["views"]))

                if stats.get("views_delta") is not None:
                    total_views_delta += stats["views_delta"]

            results.append(
                format_stats(stats)
            )

        except Exception as e:

            print("\n" + "=" * 80)
            print(f"Ошибка при обработке ссылки:\n{url}\n")
            traceback.print_exc()
            print("=" * 80 + "\n")

            results.append(
                f"❌ {e}\n{url}"
            )

            views_for_copy.append("N/A")

    if not results:
        return None, 0, new_snapshots

    message = "\n\n━━━━━━━━━━━━━━\n\n".join(results)

    if len(results) > 1:

        message += (
            "\n\n━━━━━━━━━━━━━━\n\n"
            f"📊 <b>Общий охват</b>\n\n"
            f"👀 <code>{total_views}</code>{fmt_delta(total_views_delta)}\n\n"

            "📋 <b>Охваты для таблицы</b>\n\n"
            "<pre>"
            + "\n".join(views_for_copy)
            + "</pre>"
        )

        if budget:

            cpv = budget / total_views if total_views else 0

            previous_total_views = total_views - total_views_delta

            cpv_delta = None

            if total_views_delta and previous_total_views > 0:
                previous_cpv = budget / previous_total_views
                cpv_delta = cpv - previous_cpv

            message += (
                "\n\n"
                f"💰 <b>Бюджет:</b> {format_money(budget)} ₽\n"
                f"📈 <b>CPV:</b> {cpv:.4f} ₽{fmt_float_delta(cpv_delta)}"
            )

        else:
            message += (
                "\n\n📊 Хочешь посчитать CPV? Ответь на это сообщение "
                "командой <code>/budget</code>"
            )

        if not has_title:
            message += (
                "\n\n📝 Хочешь добавить название проекта? "
                "Ответь на это сообщение командой <code>/title</code> — "
                "можно сразу с ссылкой на отчет, и название станет гиперссылкой."
            )

    return message, total_views, new_snapshots


REFRESH_KEYBOARD = InlineKeyboardMarkup([[
    InlineKeyboardButton("🔄 Обновить", callback_data="refresh")
]])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    urls = extract_urls(update.message.text)

    await log_message(update.effective_chat.id, update.message.message_id)

    # Пользователь прислал название после команды /title
    if user_id in pending_title:

        # Если прислали голую ссылку (без текста) — это новый запрос
        # статистики, а не название. Если ссылка идет с текстом —
        # считаем это названием с гиперссылкой.
        if is_bare_url_message(text):
            del pending_title[user_id]

        else:

            pending = pending_title.pop(user_id)

            entry = await load_message_data(pending["message_id"])

            if not entry:
                await reply_and_log(
                    update,
                    "Не нашел данные по этому сообщению — оно устарело."
                )
                return

            title = text.strip()

            await apply_title(
                context.bot,
                pending["chat_id"],
                pending["message_id"],
                entry,
                title,
            )

            await reply_and_log(update, f"Готово, назвал: «{title}» ✅")

            return

    # Пользователь прислал бюджет после команды /budget
    if user_id in pending_budget:

        # Если прислали ссылку — это новый запрос статистики, отменяем ожидание.
        if extract_urls(text):
            del pending_budget[user_id]

        else:

            pending = pending_budget.pop(user_id)

            budget = parse_budget(text)

            if budget is None:
                await reply_and_log(
                    update,
                    "Не понял бюджет, пришли просто число в рублях."
                )
                return

            entry = await load_message_data(pending["message_id"])

            if not entry:
                await reply_and_log(
                    update,
                    "Не нашел данные по этому сообщению — оно устарело."
                )
                return

            await apply_budget(
                context.bot,
                pending["chat_id"],
                pending["message_id"],
                entry,
                budget,
            )

            await reply_and_log(update, f"Готово, посчитал CPV на бюджет {format_money(budget)} ₽ ✅")

            return

    if not urls:

        await reply_and_log(
            update,
            "Не нашел ни одной ссылки 😔"
        )

        return

    await track_user(user_id)

    message, total_views, snapshots = await build_message(urls)

    if message is None:

        await reply_and_log(
            update,
            "Не нашел поддерживаемых ссылок."
        )

        return

    sent = await update.message.reply_text(
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=REFRESH_KEYBOARD,
    )

    await log_message(update.effective_chat.id, sent.message_id, is_stat=True)
    await save_message_data(sent.message_id, urls, snapshots, base_text=message)


async def handle_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    message_id = query.message.message_id

    entry = await load_message_data(message_id)

    if not entry:
        await query.answer("Ссылки устарели, пришли заново 😔", show_alert=True)
        return

    await query.answer("Обновляю…")

    title = entry.get("title")
    budget = entry.get("budget")

    message, total_views, new_snapshots = await build_message(
        entry["urls"],
        entry["snapshots"],
        has_title=bool(title),
        budget=budget,
    )

    if message is None:
        return

    await save_message_data(
        message_id,
        entry["urls"],
        new_snapshots,
        title=title,
        base_text=message,
        budget=budget,
    )

    if title:
        message = f"{title}\n\n" + message

    try:
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=REFRESH_KEYBOARD,
        )
    except Exception as e:
        # Telegram кидает ошибку, если текст не поменялся
        if "message is not modified" not in str(e):
            raise


async def post_init(app):

    try:
        await start_telegram_client()
    except Exception:
        print("\n" + "=" * 80)
        print("Ошибка запуска Telethon:\n")
        traceback.print_exc()
        print("=" * 80 + "\n")


app = (
    ApplicationBuilder()
    .token(TOKEN)
    .post_init(post_init)
    .build()
)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("title", cmd_title))
app.add_handler(CommandHandler("budget", cmd_budget))
app.add_handler(CommandHandler("stats", cmd_stats))
app.add_handler(CommandHandler("clean", cmd_clean))

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message,
    )
)

app.add_handler(CallbackQueryHandler(handle_refresh, pattern="^refresh$"))

print("🚀 REACHBITCH запущен")

app.run_polling(drop_pending_updates=True)
