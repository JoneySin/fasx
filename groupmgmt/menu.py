"""
🎛 GROUP MANAGER MENU (Control Panel + PM Experience)
======================================================

Do kaam karta hai:

1. 👥 <b>Group control panel</b> (``/gm``) — group admins ke liye inline
   buttons: manager on/off, delete-on-violation, warn limit, aur saare
   block-lists ka live status.
2. 💬 <b>PM experience</b> — ``build_gm_menu()`` se wahi panel banata hai jo
   free / premium users ko ``/start`` par dikhta hai (features + buttons +
   neeche premium-join button).
"""

import logging

from hydrogram import Client, filters
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from groupmgmt.core import (
    S_ALLOW_LINKS, S_BLOCK_LINKS, S_BLOCK_MEDIA, S_DELETE, S_ENABLED, S_LANGS,
    S_WARN_LIMIT, S_WORDS, esc, get_gm_settings, is_admin, set_gm_setting,
    toggle_gm_setting,
)
from groupmgmt.language import languages_text
from Script import script
from utils import temp

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 🛠 PM GROUP-MANAGER MENU
# ─────────────────────────────────────────────
def build_gm_menu(user_id, premium=False, is_admin_user=False):
    """PM me Group-Manager experience ka (text, markup) pair banata hai."""
    rows = [
        [InlineKeyboardButton("🛡️ Group Manager Features", callback_data="gm_features")],
        [InlineKeyboardButton("➕ Add to Group", url=f"https://t.me/{temp.U_NAME}?startgroup=start")],
        [InlineKeyboardButton("📘 GM Help", callback_data="gm_help"),
         InlineKeyboardButton("📊 Global Stats", callback_data="stats")],
    ]
    if is_admin_user or premium:
        rows.append([InlineKeyboardButton("🔄 Switch Bot Mode", callback_data="mode_open")])
    rows.append([InlineKeyboardButton("💎 Join Premium", callback_data="activate_plan")])

    return script.GM_START_TXT, InlineKeyboardMarkup(rows)


# ─────────────────────────────────────────────
# 👥 GROUP CONTROL PANEL
# ─────────────────────────────────────────────
def build_panel_markup(settings):
    """Control-panel ke inline buttons (current values ke saath)."""
    enabled = settings.get(S_ENABLED, True)
    delete_on = settings.get(S_DELETE, True)
    limit = int(settings.get(S_WARN_LIMIT, 3) or 3)

    words = settings.get(S_WORDS) or []
    links = settings.get(S_BLOCK_LINKS) or []
    allows = settings.get(S_ALLOW_LINKS) or []
    media = settings.get(S_BLOCK_MEDIA) or []
    langs = settings.get(S_LANGS) or []

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🛡️ Manager: {'✅ ON' if enabled else '❌ OFF'}",
                callback_data="gm_toggle#mgmt_enabled"),
            InlineKeyboardButton(
                f"🗑 Delete: {'✅ ON' if delete_on else '❌ OFF'}",
                callback_data="gm_toggle#delete_on_violation"),
        ],
        [
            InlineKeyboardButton("🎚 Warn Limit: -", callback_data="gm_limit#down"),
            InlineKeyboardButton(f"🎚 {limit}", callback_data="gm_noop"),
            InlineKeyboardButton("🎚 Warn Limit: +", callback_data="gm_limit#up"),
        ],
        [
            InlineKeyboardButton(f"🚫 Words ({len(words)})", callback_data="gm_list#words"),
            InlineKeyboardButton(f"🔗 Links ({len(links)})", callback_data="gm_list#links"),
        ],
        [
            InlineKeyboardButton(f"✅ Allowed ({len(allows)})", callback_data="gm_list#allow"),
            InlineKeyboardButton(f"🖼 Media ({len(media)})", callback_data="gm_list#media"),
        ],
        [
            InlineKeyboardButton(f"🌍 Langs ({len(langs)})", callback_data="gm_list#langs"),
            InlineKeyboardButton("🚫 Banned Users", callback_data="gm_list#bans"),
        ],
        [InlineKeyboardButton("❌ Close Panel", callback_data="gm_close")],
    ])


def _antiflood_text(settings):
    """Antiflood ki live status line (limit 0 = OFF)."""
    cfg = settings.get("antiflood") or {}
    limit = int(cfg.get("limit", 0) or 0) if isinstance(cfg, dict) else 0
    window = int(cfg.get("window", 10) or 10) if isinstance(cfg, dict) else 10
    return f"ON ({limit}/{window}s)" if limit else "OFF"


def build_panel_text(settings, chat=None):
    """Control-panel ka text (live counts ke saath)."""
    words = settings.get(S_WORDS) or []
    links = settings.get(S_BLOCK_LINKS) or []
    allows = settings.get(S_ALLOW_LINKS) or []
    media = settings.get(S_BLOCK_MEDIA) or []
    langs = settings.get(S_LANGS) or []
    banned = settings.get("banned_users") or {}

    title = f" — {esc(chat.title)}" if chat else ""

    return (
        f"🛡️ <b>Group Manager Control Panel</b>{title}\n\n"
        f"🟢 Manager: <b>{'ON' if settings.get(S_ENABLED, True) else 'OFF'}</b>\n"
        f"🗑 Delete violating msg: <b>{'ON' if settings.get(S_DELETE, True) else 'OFF'}</b>\n"
        f"🎚 Auto-ban warn limit: <b>{settings.get(S_WARN_LIMIT, 3)}</b>\n\n"
        f"🚫 Words: <b>{len(words)}</b>\n"
        f"🔗 Blocked links: <b>{len(links)}</b> (allowed: <b>{len(allows)}</b>)\n"
        f"🖼 Blocked media: <b>{len(media)}</b>\n"
        f"🌍 Languages: <b>{languages_text(langs)}</b>\n"
        f"🚫 Banned users: <b>{len(banned)}</b>\n"
        f"🌊 Antiflood: <b>{_antiflood_text(settings)}</b>\n\n"
        f"💡 Auto-filter is group me <b>OFF</b> hai (group-manager mode)."
    )


@Client.on_message(filters.command("gm") & filters.group)
async def gm_panel_cmd(client, message):
    """Group control panel kholta hai (sirf group admins)."""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye panel use kar sakte hain.")

    settings = await get_gm_settings(message.chat.id)
    await message.reply(
        build_panel_text(settings, message.chat),
        reply_markup=build_panel_markup(settings),
    )


@Client.on_callback_query(filters.regex(r"^gm_help$"))
async def gm_help_cb(client, query):
    """Group-manager help (callback se — group reply ka button bhi isi ko hit karta hai)."""
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data="back_start")],
    ])
    try:
        await query.message.edit_text(script.GM_HELP_TXT, reply_markup=markup)
    except Exception:
        try:
            await query.message.edit_caption(caption=script.GM_HELP_TXT, reply_markup=markup)
        except Exception as e:
            logger.debug(f"gm_help_cb failed: {e}")


# ─────────────────────────────────────────────
# 🎛 PANEL CALLBACKS
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^gm_toggle#"))
async def gm_toggle_cb(client, query):
    """Panel ke ON/OFF toggles."""
    try:
        chat_id = query.message.chat.id
        if not await is_admin(client, chat_id, query.from_user.id):
            return await query.answer("❌ Sirf group admins ye settings change kar sakte hain.", show_alert=True)

        key = query.data.split("#", 1)[1]
        if key not in (S_ENABLED, S_DELETE):
            return await query.answer("❌ Unknown setting.", show_alert=True)

        value = await toggle_gm_setting(chat_id, key)
        settings = await get_gm_settings(chat_id)
        await query.answer(f"✅ {'ON' if value else 'OFF'}", show_alert=False)
        await query.message.edit_text(
            build_panel_text(settings, query.message.chat),
            reply_markup=build_panel_markup(settings),
        )
    except Exception as e:
        logger.error(f"gm_toggle_cb error: {e}")


@Client.on_callback_query(filters.regex(r"^gm_limit#"))
async def gm_limit_cb(client, query):
    """Auto-ban warn limit +1 / -1."""
    try:
        chat_id = query.message.chat.id
        if not await is_admin(client, chat_id, query.from_user.id):
            return await query.answer("❌ Sirf group admins ye settings change kar sakte hain.", show_alert=True)

        action = query.data.split("#", 1)[1]
        settings = await get_gm_settings(chat_id)
        limit = int(settings.get(S_WARN_LIMIT, 3) or 3)
        limit = limit + 1 if action == "up" else limit - 1
        limit = max(0, min(20, limit))
        await set_gm_setting(chat_id, S_WARN_LIMIT, limit)

        settings = await get_gm_settings(chat_id)
        await query.answer(f"🎚 Warn limit: {limit}", show_alert=False)
        await query.message.edit_text(
            build_panel_text(settings, query.message.chat),
            reply_markup=build_panel_markup(settings),
        )
    except Exception as e:
        logger.error(f"gm_limit_cb error: {e}")


@Client.on_callback_query(filters.regex(r"^gm_list#"))
async def gm_list_cb(client, query):
    """Block-lists ka live status dikhata hai."""
    try:
        chat_id = query.message.chat.id
        if not await is_admin(client, chat_id, query.from_user.id):
            return await query.answer("❌ Sirf group admins ye list dekh sakte hain.", show_alert=True)

        what = query.data.split("#", 1)[1]
        settings = await get_gm_settings(chat_id)

        if what == "words":
            items = settings.get(S_WORDS) or []
            title = "🚫 <b>Blacklisted Words</b>"
        elif what == "links":
            items = settings.get(S_BLOCK_LINKS) or []
            title = "🔗 <b>Blocked Links</b>"
        elif what == "allow":
            items = settings.get(S_ALLOW_LINKS) or []
            title = "✅ <b>Allowed Links (Whitelist)</b>"
        elif what == "media":
            items = settings.get(S_BLOCK_MEDIA) or []
            title = "🖼 <b>Blocked Media Types</b>"
        elif what == "langs":
            items = settings.get(S_LANGS) or []
            title = "🌍 <b>Allowed Languages</b>"
        elif what == "bans":
            banned = settings.get("banned_users") or {}
            items = [f"{uid} — {rsn}" for uid, rsn in banned.items()]
            title = "🚫 <b>Banned Users</b>"
        else:
            items = []
            title = "📋 <b>List</b>"

        body = "\n".join(f"• <code>{esc(str(i))}</code>" for i in items[:60]) or "📭 Empty"

        await query.message.edit_text(
            f"{title} (<code>{len(items)}</code>)\n\n{body}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Panel", callback_data="gm_back")],
            ]),
        )
    except Exception as e:
        logger.error(f"gm_list_cb error: {e}")


@Client.on_callback_query(filters.regex(r"^gm_back$"))
async def gm_back_cb(client, query):
    """List panel se wapas control panel."""
    try:
        chat_id = query.message.chat.id
        settings = await get_gm_settings(chat_id)
        await query.message.edit_text(
            build_panel_text(settings, query.message.chat),
            reply_markup=build_panel_markup(settings),
        )
    except Exception as e:
        logger.error(f"gm_back_cb error: {e}")


@Client.on_callback_query(filters.regex(r"^gm_noop$"))
async def gm_noop_cb(client, query):
    await query.answer()


@Client.on_callback_query(filters.regex(r"^gm_close$"))
async def gm_close_cb(client, query):
    try:
        await query.message.delete()
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^gm_features$"))
async def gm_features_cb(client, query):
    """PM me feature-list dikhata hai."""
    try:
        await query.message.edit_text(
            script.GM_FEATURES_TXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="back_start")],
            ]),
        )
    except Exception:
        try:
            await query.message.edit_text(
                script.GM_FEATURES_TXT,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_start")],
                ]),
            )
        except Exception:
            pass
