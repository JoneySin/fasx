"""
🌍 LANGUAGE FILTER (Group Manager Engine)
=========================================

Group me message ki language detect karke allow-list se compare karta hai.
Detection pure Unicode-script based hai (koi external API / RAM nahi):

• Devanagari → Hindi  • Bengali → Bangla  • Tamil → Tamil
• Telugu → Telugu     • Kannada → Kannada • Malayalam → Malayalam
• Gujarati → Gujarati • Gurmukhi → Punjabi • Arabic → Arabic
• Chinese → Chinese   • Japanese (Kana) → Japanese • Korean → Korean
• Cyrillic → Russian  • Greek → Greek        • Latin → English

Admin allowed-list set karta hai (``/setlang hi,en``) — list khali ho to
filter OFF rehta hai (har message allow).
"""

import logging
import unicodedata

from hydrogram import Client, filters

from groupmgmt.core import (
    S_LANGS, get_gm_settings, gm_enabled, is_admin, set_gm_setting,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 🗺 SCRIPT RANGES → LANGUAGE CODE
# ─────────────────────────────────────────────
SCRIPT_RANGES = (
    ("hi", 0x0900, 0x097F),   # Devanagari (Hindi / Marathi / Nepali)
    ("bn", 0x0980, 0x09FF),   # Bengali
    ("pa", 0x0A00, 0x0A7F),   # Gurmukhi (Punjabi)
    ("gu", 0x0A80, 0x0AFF),   # Gujarati
    ("or", 0x0B00, 0x0B7F),   # Oriya
    ("ta", 0x0B80, 0x0BFF),   # Tamil
    ("te", 0x0C00, 0x0C7F),   # Telugu
    ("kn", 0x0C80, 0x0CFF),   # Kannada
    ("ml", 0x0D00, 0x0D7F),   # Malayalam
    ("si", 0x0D80, 0x0DFF),   # Sinhala
    ("th", 0x0E00, 0x0E7F),   # Thai
    ("lo", 0x0E80, 0x0EFF),   # Lao
    ("bo", 0x0F00, 0x0FFF),   # Tibetan
    ("my", 0x1000, 0x109F),   # Myanmar
    ("ka", 0x10A0, 0x10FF),   # Georgian
    ("hy", 0x0530, 0x058F),   # Armenian
    ("he", 0x0590, 0x05FF),   # Hebrew
    ("ar", 0x0600, 0x06FF),   # Arabic (Urdu / Persian / Arabic)
    ("el", 0x0370, 0x03FF),   # Greek
    ("ru", 0x0400, 0x04FF),   # Cyrillic
    ("ko", 0xAC00, 0xD7AF),   # Hangul
    ("ja", 0x3040, 0x30FF),   # Hiragana + Katakana
    ("zh", 0x4E00, 0x9FFF),   # CJK Unified Ideographs
)

LANGUAGE_NAMES = {
    "hi": "Hindi", "bn": "Bangla", "pa": "Punjabi", "gu": "Gujarati",
    "or": "Odia", "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
    "ml": "Malayalam", "si": "Sinhala", "th": "Thai", "lo": "Lao",
    "bo": "Tibetan", "my": "Myanmar", "ka": "Georgian", "hy": "Armenian",
    "he": "Hebrew", "ar": "Arabic", "el": "Greek", "ru": "Russian",
    "ko": "Korean", "ja": "Japanese", "zh": "Chinese", "en": "English",
    "unknown": "Unknown",
}

# Extra aliases jo admin type kar sakta hai
LANG_ALIASES = {
    "hindi": "hi", "hi": "hi", "marathi": "hi", "nepali": "hi",
    "bengali": "bn", "bangla": "bn", "bn": "bn",
    "punjabi": "pa", "pa": "pa",
    "gujarati": "gu", "gu": "gu",
    "odia": "or", "oriya": "or", "or": "or",
    "tamil": "ta", "ta": "ta",
    "telugu": "te", "te": "te",
    "kannada": "kn", "kn": "kn",
    "malayalam": "ml", "ml": "ml",
    "sinhala": "si", "si": "si",
    "thai": "th", "th": "th",
    "tibetan": "bo", "bo": "bo",
    "myanmar": "my", "my": "my",
    "georgian": "ka", "ka": "ka",
    "armenian": "hy", "hy": "hy",
    "hebrew": "he", "he": "he",
    "arabic": "ar", "urdu": "ar", "persian": "ar", "ar": "ar",
    "greek": "el", "el": "el",
    "russian": "ru", "ru": "ru",
    "korean": "ko", "ko": "ko",
    "japanese": "ja", "ja": "ja",
    "chinese": "zh", "zh": "zh",
    "english": "en", "en": "en",
}

def detect_language(text):
    """Text ki dominant language detect karta hai.

    Returns a language code from ``LANGUAGE_NAMES``. Bahut mixed / symbol-only
    text par ``"unknown"`` — jise kabhi block nahi kiya jata (warna normal
    "नमस्ते hello" jaisi lines par bhi galat action chala jata).

    ⚠️ NOTE: sirf ``str.isalpha()`` par bharosa nahi karte — Devanagari/Arabic
    jaise scripts me vowel marks (``्``, ``े``, ``َ``) Mn/Mc category ke hote
    hain aur ``isalpha()`` unhe False deta hai, jisse Hindi text galti se
    English (Latin) se chhota ginn kar English detect ho jata tha.
    """
    if not text:
        return "unknown"

    counts = {}

    for ch in text:
        cp = ord(ch)
        code = None

        for lang, lo, hi in SCRIPT_RANGES:
            if lo <= cp <= hi:
                code = lang
                break

        if code is None:
            # Latin (English) + latin-extended (accents/marks)
            if 0x0041 <= cp <= 0x024F and (ch.isalpha() or unicodedata.category(ch) == "Mn"):
                code = "en"
            else:
                continue
        elif not (ch.isalpha() or unicodedata.category(ch) in ("Mn", "Mc")):
            # Danda / punctuation jo script range me aa gaye → skip
            continue

        counts[code] = counts.get(code, 0) + 1

    if not counts:
        return "unknown"

    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    best, best_count = ranked[0]

    # Dominant script ko hi maano — agar text sach me 50/50 mixed hai (ya top
    # do scripts barabar hain) to koi action nahi ("unknown").
    if best_count * 2 < total:
        return "unknown"
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return "unknown"

    return best


def normalize_lang_codes(raw):
    """Admin ke diye gaye list ko canonical codes me convert karta hai."""
    if not raw:
        return []
    if isinstance(raw, str):
        raw = raw.replace(",", " ").split()
    out = []
    for item in raw:
        code = LANG_ALIASES.get(str(item).strip().lower())
        if code and code not in out:
            out.append(code)
    return out


def languages_text(codes):
    if not codes:
        return "OFF (koi language block nahi)"
    return ", ".join(f"{c} ({LANGUAGE_NAMES.get(c, c)})" for c in codes)


# ─────────────────────────────────────────────
# 🔍 VIOLATION CHECKER (blacklist engine ke saath use hota hai)
# ─────────────────────────────────────────────
async def check_language(text, settings=None, chat_id=None):
    """Returns (blocked, language_code).

    ``settings`` ke saath call karo (group settings). Agar settings na diya
    jaye to ``chat_id`` zaroori hai (warna filter silently OFF reh jata hai).
    """
    if settings is None:
        if chat_id is None:
            return False, "unknown"
        settings = await get_gm_settings(chat_id)

    allowed = normalize_lang_codes(settings.get(S_LANGS) or [])
    if not allowed:
        return False, "unknown"

    lang = detect_language(text)
    if lang == "unknown":
        return False, lang
    if lang in allowed:
        return False, lang
    return True, lang


# ─────────────────────────────────────────────
# ⚙️ COMMANDS
# ─────────────────────────────────────────────
@Client.on_message(filters.command(["setlang"]) & filters.group)
async def setlang_cmd(client, message):
    """Allowed languages set karta hai — ``/setlang hi,en``"""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye command use kar sakte hain.")

    if not await gm_enabled(message.chat.id):
        return await message.reply(
            "ℹ️ Ye group **Auto Filter mode** me hai — group-manager features yahan active nahi hain."
        )

    if len(message.command) < 2:
        current = normalize_lang_codes((await get_gm_settings(message.chat.id)).get(S_LANGS) or [])
        return await message.reply(
            "🌍 <b>Usage:</b> <code>/setlang hi,en,mr</code>\n\n"
            f"📌 <b>Current:</b> {languages_text(current)}\n"
            "ℹ️ Language list khali karne ke liye <code>/offlang</code> use karein."
        )

    codes = normalize_lang_codes(" ".join(message.command[1:]))
    if not codes:
        return await message.reply("❌ Language codes samajh nahi aaye. Example: <code>/setlang hi,en</code>")

    await set_gm_setting(message.chat.id, S_LANGS, codes)
    await message.reply(
        f"✅ <b>Language filter ON</b>\n\n"
        f"🌍 Allowed: <code>{languages_text(codes)}</code>\n"
        "ℹ️ Baaki languages ke messages delete + warn honge."
    )


@Client.on_message(filters.command(["offlang"]) & filters.group)
async def offlang_cmd(client, message):
    """Language filter OFF karta hai."""
    if not await is_admin(client, message.chat.id, message.from_user.id):
        return await message.reply("❌ Sirf group admins ye command use kar sakte hain.")

    await set_gm_setting(message.chat.id, S_LANGS, [])
    await message.reply("✅ <b>Language filter OFF</b> — ab har language allow hai.")


@Client.on_message(filters.command(["langs"]) & filters.group)
async def langs_cmd(client, message):
    """Current language filter + supported languages dikhata hai."""
    settings = await get_gm_settings(message.chat.id)
    current = normalize_lang_codes(settings.get(S_LANGS) or [])

    supported = ", ".join(
        f"<code>{code}</code> ({name})"
        for code, name in sorted(LANGUAGE_NAMES.items())
        if code != "unknown"
    )

    await message.reply(
        "🌍 <b>Language Filter</b>\n\n"
        f"📌 <b>Status:</b> {'✅ ON' if current else '❌ OFF'}\n"
        f"🔤 <b>Allowed:</b> {languages_text(current)}\n\n"
        f"<b>Supported codes:</b>\n{supported}\n\n"
        "ℹ️ Set karne ke liye: <code>/setlang hi,en</code>"
    )
