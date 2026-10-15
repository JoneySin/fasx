"""
🚫 BLACKLIST ENGINE (Group Manager)
====================================

Group me ye sab block hota hai:

• 🗂 <b>Words</b>      — message me forbidden words (case-insensitive)
• 🔗 <b>Links</b>      — specific domains / URLs (+ global link block + whitelist)
• 🖼 <b>Media types</b> — photo / video / document / sticker / voice / forward …
• 🌍 <b>Language</b>   — (language module se integrate)

Violation ka reaction: message delete + warning (+ limit cross hone par ban).
Sab kuch sirf tabhi chalta hai jab group ka mode ``MODE_MGMT`` ho.
"""

import logging
import re

from hydrogram import Client, filters

from groupmgmt.core import (
    MEDIA_TYPES, S_ALLOW_LINKS, S_BLOCK_LINKS, S_BLOCK_MEDIA, S_WORDS,
    esc, get_gm_settings, gm_enabled, handle_violation, is_admin, set_gm_setting,
)
from groupmgmt.language import LANGUAGE_NAMES, check_language

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 🔍 MATCHERS (pure functions — testable)
# ─────────────────────────────────────────────
def match_word(text, words):
    """Text me koi blacklisted word hai? Returns (matched_word or None)."""
    if not text or not words:
        return None
    low = text.lower()
    for raw in words:
        w = str(raw).strip().lower()
        if not w:
            continue
        if w in low:
            return raw
    return None


def extract_links(text):
    """Message ke saare links/domains nikalta hai (lowercase list)."""
    if not text:
        return []
    found = []
    for m in re.finditer(
        r"(?:https?://[^\s<>\"']+|www\.[^\s<>\"']+|(?:t\.me|telegram\.me)/[^\s<>\"']+"
        r"|(?:[\w-]+\.)+[a-z]{2,}(?:/[^\s<>\"']*)?)",
        text,
        re.IGNORECASE,
    ):
        link = m.group(0).strip().rstrip(".,!?")
        if link:
            found.append(link.lower())
    return found


def _domain_of(link):
    """Link ka domain nikalta hai (t.me/xyz → t.me)."""
    link = link.lower().strip()
    link = re.sub(r"^https?://", "", link)
    link = re.sub(r"^www\.", "", link)
    return link.split("/")[0]


def is_link_allowed(link, allow_list):
    """Whitelist check — domain ya full-link match."""
    link = link.lower().strip()
    domain = _domain_of(link)
    for raw in allow_list or []:
        allow = str(raw).strip().lower()
        if not allow:
            continue
        allow_domain = _domain_of(allow)
        if domain == allow_domain or link.startswith(allow) or domain.endswith("." + allow_domain):
            return True
    return False


def is_link_blocked(link, block_list, allow_list):
    """Blocked-link check (whitelist pehle)."""
    if is_link_allowed(link, allow_list):
        return False
    link = link.lower().strip()
    domain = _domain_of(link)
    for raw in block_list or []:
        blocked = str(raw).strip().lower()
        if not blocked:
            continue
        blocked_domain = _domain_of(blocked)
        if link == blocked or domain == blocked_domain or domain.endswith("." + blocked_domain):
            return True
        if blocked in link:
            return True
    return False


def detect_media_types(message):
    """Message me kaun-kaun se media types hain (list)."""
    found = []
    if getattr(message, "photo", None):
        found.append("photo")
    if getattr(message, "video", None):
        found.append("video")
    if getattr(message, "document", None):
        found.append("document")
    if getattr(message, "sticker", None):
        found.append("sticker")
    if getattr(message, "voice", None):
        found.append("voice")
    if getattr(message, "animation", None):
        found.append("animation")
    if getattr(message, "audio", None):
        found.append("audio")
    if getattr(message, "video_note", None):
        found.append("video_note")
    if getattr(message, "forward_date", None) or getattr(message, "forward_from", None):
        found.append("forward")
    if getattr(message, "contact", None):
        found.append("contact")
    return found


def match_media(message, blocked_media):
    """Blocked media types me se kaun sa message me hai."""
    if not blocked_media:
        return None
    present = detect_media_types(message)
    for b in blocked_media:
        b = str(b).strip().lower()
        if b and b in present:
            return b
    return None


# ─────────────────────────────────────────────
# 🕵️ MAIN ENFORCEMENT HANDLER
# ─────────────────────────────────────────────
@Client.on_message(filters.group & filters.incoming & ~filters.command(["id", "report"]))
async def blacklist_enforcer(client, message):
    """Group me aane wale har message ko blacklists ke against check karta hai."""
    try:
        if not await gm_enabled(message.chat.id):
            return

        settings = await get_gm_settings(message.chat.id)
        user = message.from_user
        if not user or user.is_bot:
            return

        text = message.text or message.caption or ""

        # 1️⃣ Word blacklist
        words = settings.get(S_WORDS) or []
        hit = match_word(text, words)
        if hit:
            await handle_violation(client, message, f"Blacklisted word: <code>{esc(hit)}</code>", settings)
            return

        # 2️⃣ Link blacklist (+ whitelist)
        block_links = settings.get(S_BLOCK_LINKS) or []
        allow_links = settings.get(S_ALLOW_LINKS) or []
        links = extract_links(text)
        if links:
            for link in links:
                if is_link_blocked(link, block_links, allow_links):
                    await handle_violation(
                        client, message, f"Blocked link: <code>{esc(link)}</code>", settings)
                    return

        # 3️⃣ Media-type blacklist
        hit_media = match_media(message, settings.get(S_BLOCK_MEDIA) or [])
        if hit_media:
            await handle_violation(
                client, message, f"Blocked media type: <code>{esc(hit_media)}</code>", settings)
            return

        # 4️⃣ Language filter
        blocked, lang = await check_language(text, settings)
        if blocked:
            name = LANGUAGE_NAMES.get(lang, lang)
            await handle_violation(
                client, message, f"Blocked language: <code>{esc(name)}</code>", settings)
            return

    except Exception as e:
        logger.error(f"blacklist_enforcer error: {e}")


# ─────────────────────────────────────────────
# ⚙️ COMMANDS — WORDS
# ─────────────────────────────────────────────
@Client.on_message(filters.command(["addword"]) & filters.group)
async def add_word_cmd(client, message):
    """Blacklisted word add karta hai — ``/addword word``"""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye command use kar sakte hain.")
    if not await gm_enabled(message.chat.id):
        return await message.reply("ℹ️ Ye group **Auto Filter mode** me hai — group-manager features yahan active nahi hain.")
    if len(message.command) < 2:
        return await message.reply("⚠️ <b>Usage:</b> <code>/addword badword</code>")

    word = " ".join(message.command[1:]).strip().lower()
    if not word:
        return await message.reply("⚠️ Koi word diya nahi.")

    settings = await get_gm_settings(message.chat.id)
    words = list(settings.get(S_WORDS) or [])
    if word in words:
        return await message.reply(f"ℹ️ <code>{esc(word)}</code> pehle se list me hai.")

    words.append(word)
    await set_gm_setting(message.chat.id, S_WORDS, words)
    await message.reply(f"✅ <code>{esc(word)}</code> blacklisted words me add ho gaya.\n📊 Total: <code>{len(words)}</code>")


@Client.on_message(filters.command(["rmword"]) & filters.group)
async def rm_word_cmd(client, message):
    """Blacklisted word hatata hai — ``/rmword word``"""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye command use kar sakte hain.")
    if len(message.command) < 2:
        return await message.reply("⚠️ <b>Usage:</b> <code>/rmword badword</code>")

    word = " ".join(message.command[1:]).strip().lower()
    settings = await get_gm_settings(message.chat.id)
    words = list(settings.get(S_WORDS) or [])
    if word not in words:
        return await message.reply(f"ℹ️ <code>{esc(word)}</code> list me hai hi nahi.")

    words.remove(word)
    await set_gm_setting(message.chat.id, S_WORDS, words)
    await message.reply(f"✅ <code>{esc(word)}</code> remove ho gaya.\n📊 Total: <code>{len(words)}</code>")


@Client.on_message(filters.command(["words"]) & filters.group)
async def list_words_cmd(client, message):
    """Blacklisted words ki list."""
    settings = await get_gm_settings(message.chat.id)
    words = settings.get(S_WORDS) or []
    if not words:
        return await message.reply("📭 Abhi koi blacklisted word nahi hai.")

    text = "\n".join(f"• <code>{esc(w)}</code>" for w in words[:100])
    await message.reply(f"🚫 <b>Blacklisted Words</b> (<code>{len(words)}</code>)\n\n{text}")


# ─────────────────────────────────────────────
# ⚙️ COMMANDS — LINKS
# ─────────────────────────────────────────────
@Client.on_message(filters.command(["addlink"]) & filters.group)
async def add_link_cmd(client, message):
    """Blocked link/domain add karta hai — ``/addlink example.com``"""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye command use kar sakte hain.")
    if len(message.command) < 2:
        return await message.reply("⚠️ <b>Usage:</b> <code>/addlink example.com</code>")

    link = " ".join(message.command[1:]).strip().lower()
    settings = await get_gm_settings(message.chat.id)
    links = list(settings.get(S_BLOCK_LINKS) or [])
    if link in links:
        return await message.reply("ℹ️ Ye link pehle se blocked hai.")

    links.append(link)
    await set_gm_setting(message.chat.id, S_BLOCK_LINKS, links)
    await message.reply(f"✅ <code>{esc(link)}</code> blocked links me add ho gaya.\n📊 Total: <code>{len(links)}</code>")


@Client.on_message(filters.command(["rmlink"]) & filters.group)
async def rm_link_cmd(client, message):
    """Blocked link hatata hai."""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye command use kar sakte hain.")
    if len(message.command) < 2:
        return await message.reply("⚠️ <b>Usage:</b> <code>/rmlink example.com</code>")

    link = " ".join(message.command[1:]).strip().lower()
    settings = await get_gm_settings(message.chat.id)
    links = list(settings.get(S_BLOCK_LINKS) or [])
    if link not in links:
        return await message.reply("ℹ️ Ye link blocked list me hai hi nahi.")

    links.remove(link)
    await set_gm_setting(message.chat.id, S_BLOCK_LINKS, links)
    await message.reply(f"✅ <code>{esc(link)}</code> remove ho gaya.")


@Client.on_message(filters.command(["links"]) & filters.group)
async def list_links_cmd(client, message):
    """Blocked + allowed links ki list."""
    settings = await get_gm_settings(message.chat.id)
    blocked = settings.get(S_BLOCK_LINKS) or []
    allowed = settings.get(S_ALLOW_LINKS) or []

    text = "🔗 <b>Link Filter</b>\n\n"
    text += f"🚫 <b>Blocked:</b> <code>{len(blocked)}</code>\n"
    if blocked:
        text += "\n".join(f"• <code>{esc(b)}</code>" for b in blocked[:50]) + "\n"
    text += f"\n✅ <b>Allowed (whitelist):</b> <code>{len(allowed)}</code>\n"
    if allowed:
        text += "\n".join(f"• <code>{esc(a)}</code>" for a in allowed[:50]) + "\n"
    text += "\nℹ️ Add: <code>/addlink domain</code> • Allow: <code>/allowlink domain</code>"

    await message.reply(text)


@Client.on_message(filters.command(["allowlink"]) & filters.group)
async def allow_link_cmd(client, message):
    """Whitelist me link add karta hai (blacklist ke against)."""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye command use kar sakte hain.")
    if len(message.command) < 2:
        return await message.reply("⚠️ <b>Usage:</b> <code>/allowlink example.com</code>")

    link = " ".join(message.command[1:]).strip().lower()
    settings = await get_gm_settings(message.chat.id)
    allowed = list(settings.get(S_ALLOW_LINKS) or [])
    if link in allowed:
        return await message.reply("ℹ️ Ye link pehle se allow-list me hai.")

    allowed.append(link)
    await set_gm_setting(message.chat.id, S_ALLOW_LINKS, allowed)
    await message.reply(f"✅ <code>{esc(link)}</code> allow-list me add ho gaya.")


@Client.on_message(filters.command(["rmallow"]) & filters.group)
async def rm_allow_cmd(client, message):
    """Allow-list se link hatata hai."""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye command use kar sakte hain.")
    if len(message.command) < 2:
        return await message.reply("⚠️ <b>Usage:</b> <code>/rmallow example.com</code>")

    link = " ".join(message.command[1:]).strip().lower()
    settings = await get_gm_settings(message.chat.id)
    allowed = list(settings.get(S_ALLOW_LINKS) or [])
    if link not in allowed:
        return await message.reply("ℹ️ Ye link allow-list me hai hi nahi.")

    allowed.remove(link)
    await set_gm_setting(message.chat.id, S_ALLOW_LINKS, allowed)
    await message.reply(f"✅ <code>{esc(link)}</code> allow-list se remove ho gaya.")


# ─────────────────────────────────────────────
# ⚙️ COMMANDS — MEDIA TYPES
# ─────────────────────────────────────────────
@Client.on_message(filters.command(["blockmedia", "unblockmedia"]) & filters.group)
async def block_media_cmd(client, message):
    """Blocked media types set hatata hai — ``/blockmedia photo,video``

    ``/unblockmedia photo`` se koi media type wapas allow ho jata hai.
    """
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye command use kar sakte hain.")

    if len(message.command) < 2:
        settings = await get_gm_settings(message.chat.id)
        blocked = settings.get(S_BLOCK_MEDIA) or []
        text = "🖼 <b>Media Block List</b>\n\n"
        text += (f"🚫 <b>Blocked:</b> <code>{', '.join(blocked) if blocked else 'None'}</code>\n\n"
                 f"📌 <b>Available:</b> <code>{', '.join(MEDIA_TYPES)}</code>\n\n"
                 "ℹ️ Usage: <code>/blockmedia photo,video</code>")
        return await message.reply(text)

    raw = " ".join(message.command[1:]).lower().replace(",", " ")
    wanted = [w for w in raw.split() if w in MEDIA_TYPES]
    if not wanted:
        return await message.reply(
            f"❌ Galat media type.\n📌 Available: <code>{', '.join(MEDIA_TYPES)}</code>")

    settings = await get_gm_settings(message.chat.id)
    blocked = list(settings.get(S_BLOCK_MEDIA) or [])

    if message.command[0] == "unblockmedia":
        for w in wanted:
            if w in blocked:
                blocked.remove(w)
        await set_gm_setting(message.chat.id, S_BLOCK_MEDIA, blocked)
        return await message.reply(f"✅ <code>{', '.join(wanted)}</code> media block-list se hata diya gaya.")

    for w in wanted:
        if w not in blocked:
            blocked.append(w)
    await set_gm_setting(message.chat.id, S_BLOCK_MEDIA, blocked)
    await message.reply(f"✅ <code>{', '.join(wanted)}</code> ab block honge.\n📊 Total: <code>{len(blocked)}</code>")
