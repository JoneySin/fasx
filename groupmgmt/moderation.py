"""
🔨 MODERATION ENGINE (Group Manager)
====================================

Group admins ke liye complete moderation toolkit:

• ⚠️ ``/warn``          — user ko warning (reply-based)
• 📋 ``/warnings``       — user ki current warning count
• ♻️ ``/resetwarn``      — warnings reset
• 🎚 ``/setwarnlimit``   — auto-ban limit set
• 🚫 ``/ban`` / ``/unban``
• 🔇 ``/mute`` / ``/unmute``
• 👢 ``/kick``
• 🧹 ``/purge``         — bulk message delete
• 🔒 ``/lock`` / ``/unlock``
• 🐢 ``/slowmode``      — slow mode seconds

Sab commands sirf group-admin (ya bot-admin) ke liye, aur sirf
``MODE_MGMT`` wale groups me.
"""

import logging

from hydrogram import Client, filters

from groupmgmt.core import (
    S_WARN_LIMIT, ban_member, delete_message, esc, get_gm_settings, get_warn_count,
    gm_enabled, is_admin, kick_member, lock_chat, mute_member, purge_messages,
    reset_warn, set_gm_setting, set_slowmode, unban_member, unmute_member,
)
from database.users_chats_db import db
from info import ADMINS

logger = logging.getLogger(__name__)

MODE_HINT = (
    "ℹ️ Ye group <b>Auto Filter mode</b> me hai — group-manager features "
    "yahan active nahi hain."
)


async def _target_user(client, message):
    """Reply / mention / id se target user nikalta hai."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    if len(message.command) > 1:
        raw = message.command[1].strip()
        if raw.startswith("@"):
            raw = raw[1:]
        if raw.lstrip("-").isdigit():
            try:
                return await client.get_users(int(raw))
            except Exception:
                return None
    return None


async def _guard(client, message):
    """Common permission + mode gate. Returns True agar command chalana hai."""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        await message.reply("❌ Sirf group admins ye command use kar sakte hain.")
        return False
    if not await gm_enabled(message.chat.id):
        await message.reply(MODE_HINT)
        return False
    return True


# ─────────────────────────────────────────────
# ⚠️ WARN SYSTEM
# ─────────────────────────────────────────────
@Client.on_message(filters.command(["warn"]) & filters.group)
async def warn_cmd(client, message):
    """User ko warn karta hai — ``/warn [reason]`` (reply-based)"""
    if not await _guard(client, message):
        return

    target = await _target_user(client, message)
    if not target:
        return await message.reply("⚠️ Kisi user ko reply karke use karein.")

    reason = " ".join(message.command[1:]) if len(message.command) > 1 else "Rules violation"
    if message.reply_to_message and message.reply_to_message.text:
        reason = message.reply_to_message.text[:200]

    settings = await get_gm_settings(message.chat.id)
    limit = int(settings.get(S_WARN_LIMIT, 3) or 3)

    count = await get_warn_count(message.chat.id, target.id) + 1
    await db.set_warn(target.id, message.chat.id, {"count": count, "reason": reason})

    await delete_message(client, message.chat.id, message.reply_to_message.id if message.reply_to_message else message.id)

    if limit > 0 and count >= limit:
        if await ban_member(client, message.chat.id, target.id, reason):
            await reset_warn(message.chat.id, target.id)
            return await message.reply(
                f"🔨 <b>{esc(target.first_name or 'User')}</b> ko ban kar diya gaya "
                f"(warning limit {count}/{limit} poori hui)."
            )

    await message.reply(
        f"⚠️ <b>{esc(target.first_name or 'User')}</b> ko warning di gayi.\n"
        f"🔢 Warning: <code>{count}/{limit}</code>\n📝 Reason: <code>{esc(reason[:120])}</code>"
    )


@Client.on_message(filters.command(["warnings"]) & filters.group)
async def warnings_cmd(client, message):
    """User ki warning count dikhata hai."""
    target = await _target_user(client, message)
    if not target:
        return await message.reply("⚠️ Kisi user ko reply karke use karein.")

    count = await get_warn_count(message.chat.id, target.id)
    settings = await get_gm_settings(message.chat.id)
    limit = int(settings.get(S_WARN_LIMIT, 3) or 3)
    await message.reply(
        f"📋 <b>Warning Status</b>\n\n"
        f"👤 User: {target.mention}\n"
        f"🔢 Warnings: <code>{count}</code>\n"
        f"🎚 Limit: <code>{limit}</code>"
    )


@Client.on_message(filters.command(["resetwarn"]) & filters.group)
async def resetwarn_cmd(client, message):
    """User ki warnings reset karta hai."""
    if not await _guard(client, message):
        return

    target = await _target_user(client, message)
    if not target:
        return await message.reply("⚠️ Kisi user ko reply karke use karein.")

    await reset_warn(message.chat.id, target.id)
    await message.reply(f"✅ <b>{esc(target.first_name or 'User')}</b> ki saari warnings reset ho gayi.")


@Client.on_message(filters.command(["setwarnlimit"]) & filters.group)
async def setwarnlimit_cmd(client, message):
    """Auto-ban limit set karta hai — ``/setwarnlimit 5``"""
    if not await _guard(client, message):
        return

    if len(message.command) < 2 or not message.command[1].isdigit():
        current = int((await get_gm_settings(message.chat.id)).get(S_WARN_LIMIT, 3) or 3)
        return await message.reply(
            f"⚠️ <b>Usage:</b> <code>/setwarnlimit 5</code>\n📌 Current limit: <code>{current}</code>")

    limit = int(message.command[1])
    if limit < 0 or limit > 20:
        return await message.reply("❌ Limit 0 se 20 ke beech honi chahiye.")

    await set_gm_setting(message.chat.id, S_WARN_LIMIT, limit)
    await message.reply(f"✅ Auto-ban warning limit ab <code>{limit}</code> hai.")


# ─────────────────────────────────────────────
# 🚫 BAN / UNBAN / MUTE / KICK
# ─────────────────────────────────────────────
@Client.on_message(filters.command(["ban"]) & filters.group)
async def gban_cmd(client, message):
    """User ko group se ban karta hai — ``/ban [reason]`` (reply-based)"""
    if not await _guard(client, message):
        return

    target = await _target_user(client, message)
    if not target:
        return await message.reply("⚠️ Kisi user ko reply karke use karein.")
    if target.id in ADMINS:
        return await message.reply("❌ Bot admin ko ban nahi kar sakte.")

    reason = " ".join(message.command[1:]) if len(message.command) > 1 else "Rules violation"
    if await ban_member(client, message.chat.id, target.id, reason):
        return await message.reply(
            f"🚫 <b>{esc(target.first_name or 'User')}</b> ban ho gaya.\n📝 Reason: <code>{esc(reason[:120])}</code>")
    return await message.reply("❌ Ban nahi ho paya — bot ke permissions check karein.")


@Client.on_message(filters.command(["unban"]) & filters.group)
async def gunban_cmd(client, message):
    """User ka ban hatata hai — ``/unban <user_id>``"""
    if not await _guard(client, message):
        return

    target = await _target_user(client, message)
    if not target:
        return await message.reply("⚠️ User ID ya reply use karein.")

    if await unban_member(client, message.chat.id, target.id):
        return await message.reply(f"✅ <b>{esc(target.first_name or 'User')}</b> ka ban hat gaya.")
    return await message.reply("❌ Unban nahi ho paya.")


@Client.on_message(filters.command(["mute"]) & filters.group)
async def mute_cmd(client, message):
    """User ko mute karta hai — ``/mute [hours] [reason]`` (reply-based)"""
    if not await _guard(client, message):
        return

    target = await _target_user(client, message)
    if not target:
        return await message.reply("⚠️ Kisi user ko reply karke use karein.")

    hours = 0
    args = message.command[1:]
    if args and args[0].isdigit():
        hours = int(args[0])
        args = args[1:]
    reason = " ".join(args) or "Muted by admin"

    if await mute_member(client, message.chat.id, target.id, reason, hours):
        when = f"for <b>{hours} hours</b>" if hours else "permanently"
        return await message.reply(f"🔇 <b>{esc(target.first_name or 'User')}</b> muted {when}.")
    return await message.reply("❌ Mute nahi ho paya — bot ke permissions check karein.")


@Client.on_message(filters.command(["unmute"]) & filters.group)
async def unmute_cmd(client, message):
    """User ka mute hatata hai."""
    if not await _guard(client, message):
        return

    target = await _target_user(client, message)
    if not target:
        return await message.reply("⚠️ User ID ya reply use karein.")

    if await unmute_member(client, message.chat.id, target.id):
        return await message.reply(f"🔊 <b>{esc(target.first_name or 'User')}</b> ka mute hat gaya.")
    return await message.reply("❌ Unmute nahi ho paya.")


@Client.on_message(filters.command(["kick"]) & filters.group)
async def kick_cmd(client, message):
    """User ko group se nikal deta hai (reply-based)."""
    if not await _guard(client, message):
        return

    target = await _target_user(client, message)
    if not target:
        return await message.reply("⚠️ Kisi user ko reply karke use karein.")
    if target.id in ADMINS:
        return await message.reply("❌ Bot admin ko kick nahi kar sakte.")

    if await kick_member(client, message.chat.id, target.id):
        return await message.reply(f"👢 <b>{esc(target.first_name or 'User')}</b> group se kick ho gaya.")
    return await message.reply("❌ Kick nahi ho paya.")


# ─────────────────────────────────────────────
# 🧹 PURGE / LOCK / SLOWMODE
# ─────────────────────────────────────────────
@Client.on_message(filters.command(["purge"]) & filters.group)
async def purge_cmd(client, message):
    """Reply ke upar tak ke messages delete karta hai."""
    if not await _guard(client, message):
        return

    if not message.reply_to_message:
        return await message.reply("⚠️ Jis message tak delete karna hai uspar reply karein.")

    count = await purge_messages(client, message.chat.id, message.reply_to_message.id)
    await message.reply(f"🧹 <code>{count}</code> messages delete ho gaye.")


@Client.on_message(filters.command(["lock"]) & filters.group)
async def lock_cmd(client, message):
    """Group me message bhejna lock karta hai."""
    if not await _guard(client, message):
        return

    if await lock_chat(client, message.chat.id, True):
        return await message.reply("🔒 <b>Group locked</b> — ab members message nahi bhej sakte.")
    return await message.reply("❌ Lock nahi ho paya — bot ke permissions check karein.")


@Client.on_message(filters.command(["unlock"]) & filters.group)
async def unlock_cmd(client, message):
    """Group ka lock hatata hai."""
    if not await _guard(client, message):
        return

    if await lock_chat(client, message.chat.id, False):
        return await message.reply("🔓 <b>Group unlocked</b> — members ab message bhej sakte hain.")
    return await message.reply("❌ Unlock nahi ho paya.")


@Client.on_message(filters.command(["slowmode"]) & filters.group)
async def slowmode_cmd(client, message):
    """Slow mode set karta hai — ``/slowmode 30``"""
    if not await _guard(client, message):
        return

    if len(message.command) < 2 or not message.command[1].isdigit():
        return await message.reply("⚠️ <b>Usage:</b> <code>/slowmode 30</code> (0 = off)")

    seconds = int(message.command[1])
    if seconds < 0 or seconds > 3600:
        return await message.reply("❌ Slow mode 0 se 3600 seconds ke beech honi chahiye.")

    if await set_slowmode(client, message.chat.id, seconds):
        return await message.reply(f"🐢 Slow mode <code>{seconds}s</code> set ho gaya.")
    return await message.reply("❌ Slow mode set nahi ho paya.")


# ─────────────────────────────────────────────
# 📋 GROUP BAN LIST
# ─────────────────────────────────────────────
@Client.on_message(filters.command(["banlist"]) & filters.group)
async def banlist_cmd(client, message):
    """Group ki ban list dikhata hai."""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye command use kar sakte hain.")

    settings = await get_gm_settings(message.chat.id)
    banned = settings.get("banned_users") or {}
    if not banned:
        return await message.reply("📭 Is group me koi user banned nahi hai.")

    lines = []
    for uid, reason in list(banned.items())[:50]:
        lines.append(f"• <code>{esc(uid)}</code> — {esc(str(reason)[:60])}")
    await message.reply(
        f"🚫 <b>Banned Users</b> (<code>{len(banned)}</code>)\n\n" + "\n".join(lines))
