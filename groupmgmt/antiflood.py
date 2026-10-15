"""
🌊 ANTIFLOOD ENGINE (Group Manager)
====================================

Per-user message-rate guard — ek user thodi der me bahut saare messages
bheje to bot usse mute + warn karta hai.

• ``/antiflood 5 10``  → 10 second me 5 message = flood
• ``/antiflood off``   → antiflood band
• ``/antiflood``       → current status

⚙️ RAM SAFE (Koyeb protected): timestamps ek bounded ``lru.LRU`` me rehte hain
(2000 entries), entry purani hote hi LRU khud flush kar deta hai. Flood detect
hone par us user ka bucket turant saaf + gc.collect() — koi leak nahi.
"""

import gc
import logging
import time

from lru import LRU

from hydrogram import Client, filters
from hydrogram.errors import FloodWait

from groupmgmt.core import (
    add_warn, delete_message, esc, get_gm_settings, gm_enabled,
    is_admin, mute_member, set_gm_setting,
)
from info import ADMINS

logger = logging.getLogger(__name__)

# settings key: {"limit": int, "window": int} — missing/0 limit = OFF
S_ANTIFLOOD = "antiflood"

DEFAULT_LIMIT = 5
DEFAULT_WINDOW = 10
MAX_LIMIT = 30
MAX_WINDOW = 300

# (chat_id, user_id) -> [timestamps...]
_FLOOD = LRU(2000)


def _bucket_key(chat_id, user_id):
    return f"{chat_id}:{user_id}"


def flood_config(settings):
    """Settings se (limit, window) nikalta hai. limit 0 = antiflood OFF."""
    cfg = settings.get(S_ANTIFLOOD) or {}
    if isinstance(cfg, dict):
        limit = int(cfg.get("limit", 0) or 0)
        window = int(cfg.get("window", DEFAULT_WINDOW) or DEFAULT_WINDOW)
    else:
        limit, window = 0, DEFAULT_WINDOW
    return max(0, limit), max(1, window)


def record_message(chat_id, user_id, limit, window, now=None):
    """Message ka timestamp record karke batao flood hua ya nahi.

    Returns ``(is_flood, count_in_window)``.
    """
    if limit <= 0:
        return False, 0

    now = time.time() if now is None else now
    key = _bucket_key(chat_id, user_id)
    stamps = list(_FLOOD.get(key) or [])

    cutoff = now - window
    stamps = [t for t in stamps if t > cutoff]
    stamps.append(now)

    if len(stamps) >= limit:
        # flood detect → bucket reset (naya window shuru)
        _FLOOD[key] = []
        return True, len(stamps)

    _FLOOD[key] = stamps
    return False, len(stamps)


def reset_user(chat_id, user_id):
    _FLOOD.pop(_bucket_key(chat_id, user_id), None)


# ─────────────────────────────────────────────
# 🕵️ ENFORCEMENT HANDLER
# ─────────────────────────────────────────────
@Client.on_message(filters.group & filters.incoming & ~filters.command(["report"]))
async def antiflood_enforcer(client, message):
    try:
        if not await gm_enabled(message.chat.id):
            return

        user = message.from_user
        if not user or user.is_bot or user.id in ADMINS:
            return

        settings = await get_gm_settings(message.chat.id)
        limit, window = flood_config(settings)
        if limit <= 0:
            return

        is_flood, count = record_message(message.chat.id, user.id, limit, window)
        if not is_flood:
            return

        # Group admins ko flood par action nahi (sirf warning)
        if await is_admin(client, message.chat.id, user.id):
            return

        await delete_message(client, message.chat.id, message.id)

        name = esc(user.first_name or "User")
        mute_minutes = max(1, window // 2)

        try:
            await mute_member(client, message.chat.id, user.id,
                              reason=f"Flooding ({count} msgs/{window}s)",
                              hours=mute_minutes / 60)
            await client.send_message(
                message.chat.id,
                f"🌊 <b>Flood detected!</b>\n\n"
                f"👤 {name} — <code>{count}</code> messages in <code>{window}s</code>.\n"
                f"🔇 Muted for <b>{mute_minutes}m</b>.",
            )
        except FloodWait as e:
            logger.warning(f"antiflood FloodWait: {e}")
            return

        await add_warn(message.chat.id, user.id, "Flooding")
        gc.collect()

    except Exception as e:
        logger.error(f"antiflood_enforcer error: {e}")


# ─────────────────────────────────────────────
# ⚙️ COMMANDS
# ─────────────────────────────────────────────
@Client.on_message(filters.command("antiflood") & filters.group)
async def antiflood_cmd(client, message):
    """``/antiflood 5 10`` set kare, ``/antiflood off`` band kare."""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye command use kar sakte hain.")
    if not await gm_enabled(message.chat.id):
        return await message.reply(
            "ℹ️ Ye group <b>Auto Filter mode</b> me hai — group-manager features "
            "yahan active nahi hain."
        )

    settings = await get_gm_settings(message.chat.id)
    limit, window = flood_config(settings)

    if len(message.command) == 1:
        status = (f"✅ ON — <code>{limit}</code> messages / <code>{window}s</code>"
                  if limit else "❌ OFF")
        return await message.reply(
            f"🌊 <b>Antiflood</b>: {status}\n\n"
            "📌 Set: <code>/antiflood 5 10</code> (5 msgs in 10s)\n"
            "📌 Off: <code>/antiflood off</code>"
        )

    arg = message.command[1].lower()
    if arg in ("off", "0", "disable", "no"):
        await set_gm_setting(message.chat.id, S_ANTIFLOOD, {"limit": 0, "window": window})
        return await message.reply("✅ <b>Antiflood OFF</b>")

    if not arg.isdigit():
        return await message.reply("❌ <b>Usage:</b> <code>/antiflood 5 10</code> ya <code>/antiflood off</code>")

    limit = int(arg)
    window = int(message.command[2]) if len(message.command) > 2 and message.command[2].isdigit() else DEFAULT_WINDOW

    if limit < 2 or limit > MAX_LIMIT:
        return await message.reply(f"❌ Limit <code>2</code> se <code>{MAX_LIMIT}</code> ke beech honi chahiye.")
    if window < 2 or window > MAX_WINDOW:
        return await message.reply(f"❌ Window <code>2</code> se <code>{MAX_WINDOW}</code> seconds ke beech honi chahiye.")

    await set_gm_setting(message.chat.id, S_ANTIFLOOD, {"limit": limit, "window": window})
    await message.reply(
        f"✅ <b>Antiflood ON</b>\n\n"
        f"🌊 <code>{limit}</code> messages in <code>{window}s</code> → "
        f"message delete + mute + warning."
    )
