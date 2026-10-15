"""
🧱 GROUP MANAGEMENT — SHARED CORE HELPERS
==========================================

Ye module baaki saare GM modules (blacklist / language / moderation /
reports / menu) ke liye common primitives deta hai:

• Mode-gate (group MANAGEMENT mode me hi features chalein)
• Settings read/write helpers
• Warn / ban / mute / kick / purge / lock / slowmode actions
• Group-admin listing (report tagging ke liye)
• Violation handler (delete + warn + auto-ban)
"""

import asyncio
import html
import logging
from datetime import datetime, timedelta

from hydrogram import enums
from hydrogram.errors import FloodWait
from hydrogram.types import ChatPermissions

from database.users_chats_db import db
from info import ADMINS
from modes import MODE_MGMT, get_group_mode
from utils import get_settings, is_check_admin, save_group_settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 🔑 SETTINGS KEYS (single source of truth)
# ─────────────────────────────────────────────
S_ENABLED = "mgmt_enabled"          # manager features on/off
S_WORDS = "blacklist"               # blocked words
S_BLOCK_LINKS = "block_links"        # blocked links / domains
S_ALLOW_LINKS = "allow_links"       # whitelisted links / domains
S_BLOCK_MEDIA = "block_media"        # blocked media types
S_LANGS = "allowed_langs"           # allowed languages ([] = filter off)
S_WARN_LIMIT = "warn_limit"         # warnings ke baad auto-ban
S_DELETE = "delete_on_violation"    # violating message delete?
S_BANNED = "banned_users"           # {uid: reason}
S_MUTED = "muted_users"             # {uid: reason}

# ─────────────────────────────────────────────
# 🧰 MISC CONSTANTS
# ─────────────────────────────────────────────
MEDIA_TYPES = (
    "photo", "video", "document", "sticker", "voice",
    "animation", "audio", "video_note", "forward", "contact",
)

def esc(text):
    """HTML-escape (group titles / user names message me daalne se pehle)."""
    return html.escape(str(text or ""), quote=False)


# ─────────────────────────────────────────────
# 🚦 MODE GATE + SETTINGS
# ─────────────────────────────────────────────
async def is_mgmt_chat(chat_id):
    """True agar is chat me group-management mode hai."""
    try:
        return (await get_group_mode(chat_id)) == MODE_MGMT
    except Exception as e:
        logger.error(f"is_mgmt_chat({chat_id}) failed: {e}")
        return False


async def gm_enabled(chat_id):
    """Mode + per-group switch dono on hone par hi features chalti hain."""
    if not await is_mgmt_chat(chat_id):
        return False
    settings = await get_settings(chat_id)
    return bool(settings.get(S_ENABLED, True))


async def get_gm_settings(chat_id):
    return await get_settings(chat_id)


async def set_gm_setting(chat_id, key, value):
    await save_group_settings(chat_id, key, value)


async def toggle_gm_setting(chat_id, key, default=True):
    """Setting ko on/off karta hai aur nayi value wapas deta hai."""
    settings = await get_gm_settings(chat_id)
    new_value = not settings.get(key, default)
    await set_gm_setting(chat_id, key, new_value)
    return new_value


# ─────────────────────────────────────────────
# 👮 ADMIN UTILS
# ─────────────────────────────────────────────
async def is_admin(client, chat_id, user_id):
    """Group admin / owner check (bot-admins ko bhi maan lete hain)."""
    if int(user_id) in ADMINS:
        return True
    return await is_check_admin(client, chat_id, user_id)


async def get_group_admin_ids(client, chat_id, limit=100):
    """Group ke admins/owners ke user-ids nikalta hai (report tagging)."""
    admins = []
    try:
        async for member in client.get_chat_members(
            chat_id,
            filter=enums.ChatMembersFilter.ADMINISTRATORS,
            limit=limit,
        ):
            status = getattr(member, "status", None)
            if status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                user = getattr(member, "user", None)
                if user and not getattr(user, "is_bot", False):
                    admins.append(user)
    except Exception as e:
        logger.debug(f"get_group_admin_ids({chat_id}) failed: {e}")
    return admins


async def build_admin_mentions(client, chat_id):
    """Report message ke liye group-admins ka mention string banata hai.

    Format: ``<a href="tg://user?id=1">Admin</a>`` — clickable + safe.
    """
    admins = await get_group_admin_ids(client, chat_id)
    if not admins:
        return ""
    return " ".join(
        f'<a href="tg://user?id={u.id}">{esc(u.first_name or "Admin")}</a>'
        for u in admins[:20]
    )


# ─────────────────────────────────────────────
# 🗑 MESSAGE ACTIONS
# ─────────────────────────────────────────────
async def delete_message(client, chat_id, message_id):
    """Message delete (permission na ho to chup-chaap fail)."""
    try:
        await client.delete_messages(chat_id, message_id)
        return True
    except Exception as e:
        logger.debug(f"delete_message({chat_id},{message_id}) failed: {e}")
        return False


async def purge_messages(client, chat_id, upto_message_id, limit=200):
    """Reply ke upar tak ke saare messages delete (bot ke aage wale)."""
    deleted = 0
    try:
        msgs = await client.get_messages(chat_id, range(upto_message_id, upto_message_id - limit, -1))
    except Exception as e:
        logger.error(f"purge get_messages failed: {e}")
        return 0

    ids = [m.id for m in msgs if m and not m.empty]
    if not ids:
        return 0

    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        try:
            await client.delete_messages(chat_id, chunk)
            deleted += len(chunk)
        except Exception as e:
            logger.debug(f"purge delete chunk failed: {e}")
    return deleted


# ─────────────────────────────────────────────
# ⚠️ WARN ENGINE
# ─────────────────────────────────────────────
async def get_warn_count(chat_id, user_id):
    """User ka current warning count (is group me)."""
    try:
        data = await db.get_warn(int(user_id), int(chat_id))
        return int(data.get("count", 0) or 0)
    except Exception as e:
        logger.error(f"get_warn_count failed: {e}")
        return 0


async def add_warn(chat_id, user_id, reason=""):
    """Warning badhata hai. Returns (count, limit)."""
    limit = int((await get_gm_settings(chat_id)).get(S_WARN_LIMIT, 3) or 3)
    count = await get_warn_count(chat_id, user_id) + 1
    try:
        await db.set_warn(int(user_id), int(chat_id), {"count": count, "reason": reason})
    except Exception as e:
        logger.error(f"set_warn failed: {e}")
    return count, limit


async def reset_warn(chat_id, user_id):
    try:
        await db.clear_warn(int(user_id), int(chat_id))
        return True
    except Exception as e:
        logger.error(f"clear_warn failed: {e}")
        return False


# ─────────────────────────────────────────────
# 🚫 BAN / MUTE / KICK
# ─────────────────────────────────────────────
async def ban_member(client, chat_id, user_id, reason=""):
    """Group me user ko ban karta hai + per-group ban-list me save."""
    try:
        await client.ban_chat_member(chat_id, user_id)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await client.ban_chat_member(chat_id, user_id)
    except Exception as e:
        logger.error(f"ban_member failed: {e}")
        return False

    banned = (await get_gm_settings(chat_id)).get(S_BANNED, {}) or {}
    banned[str(user_id)] = reason or "Banned by admin"
    await set_gm_setting(chat_id, S_BANNED, banned)
    return True


async def unban_member(client, chat_id, user_id):
    try:
        await client.unban_chat_member(chat_id, user_id)
    except Exception as e:
        logger.error(f"unban_member failed: {e}")
        return False

    banned = (await get_gm_settings(chat_id)).get(S_BANNED, {}) or {}
    banned.pop(str(user_id), None)
    await set_gm_setting(chat_id, S_BANNED, banned)
    return True


async def mute_member(client, chat_id, user_id, reason="", hours=0):
    """User ko mute (restrict) karta hai."""
    until = datetime.utcnow() + timedelta(hours=hours) if hours else datetime.utcnow()
    perms = ChatPermissions(
        can_send_messages=False,
        can_send_media_messages=False,
        can_send_other_messages=False,
        can_send_polls=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )
    try:
        await client.restrict_chat_member(chat_id, user_id, perms, until)
    except Exception as e:
        logger.error(f"mute_member failed: {e}")
        return False

    muted = (await get_gm_settings(chat_id)).get(S_MUTED, {}) or {}
    muted[str(user_id)] = reason or "Muted by admin"
    await set_gm_setting(chat_id, S_MUTED, muted)
    return True


async def unmute_member(client, chat_id, user_id):
    perms = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_other_messages=True,
        can_send_polls=True,
        can_add_web_page_previews=True,
        can_change_info=True,
        can_invite_users=True,
        can_pin_messages=True,
        can_manage_topics=True,
    )
    try:
        await client.restrict_chat_member(chat_id, user_id, perms, datetime.utcnow())
    except Exception as e:
        logger.error(f"unmute_member failed: {e}")
        return False

    muted = (await get_gm_settings(chat_id)).get(S_MUTED, {}) or {}
    muted.pop(str(user_id), None)
    await set_gm_setting(chat_id, S_MUTED, muted)
    return True


async def kick_member(client, chat_id, user_id):
    """User ko turant bahar nikalta hai (unban + ban)."""
    try:
        await client.ban_chat_member(chat_id, user_id)
    except Exception as e:
        logger.error(f"kick_member failed: {e}")
        return False
    return True


async def lock_chat(client, chat_id, locked=True):
    """Group me message bhejna lock/unlock."""
    perms = ChatPermissions(
        can_send_messages=not locked,
        can_send_media_messages=not locked,
        can_send_other_messages=not locked,
        can_send_polls=not locked,
        can_add_web_page_previews=not locked,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )
    try:
        await client.set_chat_permissions(chat_id, perms)
        return True
    except Exception as e:
        logger.error(f"lock_chat failed: {e}")
        return False


async def set_slowmode(client, chat_id, seconds):
    try:
        await client.set_slow_mode(chat_id, int(seconds))
        return True
    except Exception as e:
        logger.error(f"set_slowmode failed: {e}")
        return False


# ─────────────────────────────────────────────
# 🚨 VIOLATION HANDLER (delete + warn + auto-ban)
# ─────────────────────────────────────────────
async def handle_violation(client, message, reason, settings=None):
    """Blacklist/language violation ka standard reaction.

    1. Message delete (agar settings me ON hai)
    2. Warning count badhao
    3. Limit cross hone par auto-ban
    Returns dict: ``{"deleted": bool, "count": int, "banned": bool}``
    """
    settings = settings or await get_gm_settings(message.chat.id)
    result = {"deleted": False, "count": 0, "banned": False}

    user = message.from_user
    if not user or user.is_bot:
        return result

    # Bot-admins aur group-admins ko kabhi touch nahi karte
    if user.id in ADMINS:
        return result
    try:
        if await is_check_admin(client, message.chat.id, user.id):
            return result
    except Exception:
        pass

    if settings.get(S_DELETE, True):
        result["deleted"] = await delete_message(client, message.chat.id, message.id)

    count, limit = await add_warn(message.chat.id, user.id, reason)

    try:
        await client.send_message(
            message.chat.id,
            f"⚠️ <b>{esc(user.first_name or 'User')}</b> — {esc(reason)}\n"
            f"🔢 Warning: <code>{count}/{limit}</code>",
        )
    except Exception as e:
        logger.debug(f"violation notice failed: {e}")

    if limit > 0 and count >= limit:
        if await ban_member(client, message.chat.id, user.id, reason):
            result["banned"] = True
            try:
                await client.send_message(
                    message.chat.id,
                    f"🔨 <b>{esc(user.first_name or 'User')}</b> has been banned "
                    f"(reached {count}/{limit} warnings).",
                )
            except Exception:
                pass
            await reset_warn(message.chat.id, user.id)

    result["count"] = count
    return result
