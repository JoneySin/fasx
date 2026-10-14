"""
/forward — यूज़र-अकाउंट (userbot) से बिना "Forwarded from" टैग के वीडियो कॉपी इंजन
=============================================================================

फ्लो (पहली बार /forward):
  1. बॉट मोबाइल नंबर माँगेगा  →  2. OTP माँगेगा  →  (2FA हो तो पासवर्ड माँगेगा)
  3. लॉगिन सफल → session MongoDB में सेव (रीस्टार्ट के बाद दोबारा OTP नहीं)
  4. डेस्टिनेशन चैनल/ग्रुप ID → टेस्ट मैसेज भेजकर चेक
  5. सोर्स चैनल/ग्रुप ID → चेक: लॉगिन यूज़र वहाँ एडमिन है या नहीं
  6. सिर्फ वीडियो फाइलें पुरानी→नई क्रम में कॉपी, हर फाइल के बीच 5-20 सेकंड
     का रैंडम गैप (स्पैम/बैन सेफ)

कमांड्स:
  /forward           — फ्लो शुरू करें (सिर्फ ADMINS, सिर्फ PM)
  /forward logout    — सेव किया हुआ यूज़र लॉगिन हटाएँ
  /forward status    — लॉगिन + जॉब स्टेटस
  /fstop             — चलती हुई कॉपी जॉब रोकें

टेक्नोलॉजी: hydrogram user-client (session_string) + pyromod listen conversation.
कॉपी send_cached_media से होती है (नया मैसेज बनता है — कोई फॉरवर्ड टैग नहीं),
फेल होने पर raw ForwardMessages + drop_author=True फॉलबैक।
"""

import re
import asyncio
import random
import logging

# ─────────────────────────────────────────────────
# 🔥 CRITICAL EXPLICIT PATCH: Forced Event Loop for Pyromod & uvloop Sync
# (premium.py जैसा ही — ताकि pyromod का patching ठीक से हो)
# ─────────────────────────────────────────────────
try:
    asyncio.get_running_loop()
except RuntimeError:
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        pass
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import pyromod.listen  # noqa: F401  (side-effect: Client.listen() इसी से आता है)
from pyromod.exceptions import ListenerTimeout

from hydrogram import Client, filters, enums, raw
from hydrogram.errors import (
    FloodWait, PeerFlood, RPCError,
    SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired,
    PhoneNumberInvalid, PasswordHashInvalid, AuthKeyUnregistered,
)

from info import API_ID, API_HASH, ADMINS
from utils import safe_del
from database.users_chats_db import db

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────
# ⚙️ SEND-RATE SAFETY (Anti-Spam / Anti-Ban गार्ड)
# हर वीडियो के बीच रैंडम गैप — टेलीग्राम फ्लड/बैन से बचाव के लिए
# ─────────────────────────────────────────────────
SEND_GAP_MIN = 5     # सेकंड (न्यूनतम)
SEND_GAP_MAX = 20    # सेकंड (अधिकतम)
PHONE_RETRIES = 3
CODE_RETRIES = 3
ASK_TIMEOUT = 300    # सेकंड — हर इनपुट स्टेप का वेट-टाइमआउट

# वीडियो फाइल एक्सटेंशन (document के रूप में भेजे गए वीडियो के लिए)
VIDEO_FILE_EXTS = (
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv",
    ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".vob", ".ogv",
)


# ─────────────────────────────────────────────────
# 🧪 PURE HELPERS (unit-testable — कोई I/O नहीं)
# ─────────────────────────────────────────────────
def is_video_message(msg) -> bool:
    """सिर्फ वीडियो फाइल चाहिए — video या video-mime/एक्सटेंशन वाला document।
    photo/text/audio/sticker/round-note/gif या बाकी सब skip."""
    if getattr(msg, "video", None):
        return True
    doc = getattr(msg, "document", None)
    if doc:
        mime = (getattr(doc, "mime_type", "") or "").lower()
        name = (getattr(doc, "file_name", "") or "").lower()
        return mime.startswith("video/") or name.endswith(VIDEO_FILE_EXTS)
    return False


def normalize_phone(text):
    """'+91 98765-43210' जैसे इनपुट को '+919876543210' बनाता है; गलत हो तो None"""
    raw_digits = re.sub(r"[^\d]", "", text or "")
    if not 7 <= len(raw_digits) <= 15:
        return None
    return "+" + raw_digits


def normalize_otp(text):
    """OTP से सिर्फ अंक निकालता है ('1 2 3 4 5' / '12345')"""
    digits = re.sub(r"\D", "", text or "")
    return digits if 3 <= len(digits) <= 10 else None


def normalize_password(text):
    """2FA पासवर्ड (स्पेस सहित हो सकता है — सिर्फ trim)"""
    pw = (text or "").strip()
    return pw if pw else None


def parse_chat_ref(text):
    """चैनल/ग्रुप रेफरेंस पार्स करता है।
    स्वीकार: -1001234567890 | 12345 | @username | username | https://t.me/username
    लौटाता है: int (id) | str (username) | None"""
    t = (text or "").strip()
    if not t:
        return None
    if t.lstrip("-").isdigit():
        return int(t)
    m = re.match(
        r"^(?:@|(?:https?://)?t\.me/)?([A-Za-z][A-Za-z0-9_]{3,31})$",
        t,
    )
    return m.group(1) if m else None


def random_gap():
    """हर फाइल के बीच का रैंडम गैप (5-20 सेकंड)"""
    return random.randint(SEND_GAP_MIN, SEND_GAP_MAX)


def mask_phone(phone):
    """स्टेटस में दिखाने के लिए फोन नंबर का मिडल हिस्सा छिपाता है"""
    p = phone or ""
    if len(p) < 6:
        return "****"
    return p[:4] + "*" * (len(p) - 7) + p[-3:]


# ─────────────────────────────────────────────────
# 🗂️ RUNTIME STATE (एक समय में सिर्फ एक जॉब/फ्लो)
# ─────────────────────────────────────────────────
class _ForwardState:
    def __init__(self):
        self.busy = False          # फ्लो/जॉब चल रही है
        self.cancel = False        # /fstop ने रोकने को कहा
        self.phase = ""            # login | dest | source | send

state = _ForwardState()
_user_client = None               # कैश्ड hydrogram user-client


def _is_abort_reply(resp) -> bool:
    """बीच में /fstop या /forward टाइप करने पर वर्तमान फ्लो रद्द"""
    if not resp or not resp.text:
        return False
    cmd = resp.text.strip().split()[0].split("@")[0].lower()
    return cmd in ("/fstop", "/forward", "/fwd")


async def ask(client, message, text, timeout=ASK_TIMEOUT):
    """प्रॉम्प्ट भेजो और एडमिन के रिप्लाई का इंतज़ार करो (pyromod listen)।
    लौटाता है: reply Message | None (timeout / cancel पर)"""
    prompt = await message.reply(text)
    try:
        resp = await client.listen(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            timeout=timeout,
        )
    except ListenerTimeout:
        await message.reply("⌛ <b>टाइमआउट!</b> दोबारा /forward से शुरू करें।")
        return None
    if _is_abort_reply(resp):
        await message.reply("🛑 <b>फ्लो रद्द किया गया।</b>")
        return None
    if state.cancel:
        return None
    return resp


async def interruptible_sleep(seconds):
    """स्लीप — पर /fstop से तुरंत टूट जाती है (1-1 सेकंड की चंक्स में)"""
    end = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < end:
        if state.cancel:
            return
        await asyncio.sleep(1)


# ─────────────────────────────────────────────────
# 📱 USER-ACCOUNT (USERBOT) LOGIN ENGINE
# ─────────────────────────────────────────────────
async def _export_session(user):
    """export_session_string — sync/async दोनों वर्जन के लिए सेफ"""
    s = user.export_session_string()
    if hasattr(s, "__await__"):
        s = await s
    return s


async def get_saved_client():
    """MongoDB में सेव session से user-client कनेक्ट करता है (वैकल्पिक)।
    सेशन रद्द/एक्सपायर्ड हो तो साफ़ करके None लौटाता है।"""
    global _user_client
    if _user_client and getattr(_user_client, "is_connected", False):
        return _user_client

    rec = await db.get_forward_session()
    if not rec or not rec.get("session"):
        return None

    user = Client(
        name="fwd_user",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=rec["session"],
        in_memory=True,
        no_updates=True,
    )
    try:
        await user.connect()
        await user.get_me()          # सेशन वैलिड है या नहीं — यहीं पता चलता है
    except (AuthKeyUnregistered, RPCError, Exception) as e:
        logger.warning(f"Forward user session invalid, clearing: {e}")
        await db.clear_forward_session()
        try:
            await user.disconnect()
        except Exception:
            pass
        return None

    _user_client = user
    return user


async def warm_peer_cache(user):
    """user-client की session में सारे dialogs के peer कैश करो, ताकि बाद में
    numeric chat-id (-100...) से resolve_peer काम करे (pyrogram-स्टाइल गॉटचा)।"""
    try:
        async for _ in user.get_dialogs():
            pass
    except Exception as e:
        logger.warning(f"Dialog warmup error (non-fatal): {e}")


async def login_conversation(client, message):
    """पहली बार लॉगिन: नंबर → OTP → (2FA पासवर्ड) → session सेव।
    सफल होने पर user-client लौटाता है, वरना None."""
    global _user_client

    user = Client(
        name="fwd_user",
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True,
        no_updates=True,
    )
    await user.connect()

    try:
        # ── चरण 1: मोबाइल नंबर ──
        phone = None
        for _ in range(PHONE_RETRIES):
            resp = await ask(
                client, message,
                "📱 <b>अपना टेलीग्राम मोबाइल नंबर भेजें</b>\n"
                "उदाहरण: <code>+919876543210</code>\n\n"
                "⚠️ यह नंबर उसी अकाउंट का हो जिससे वीडियो भेजने हैं।",
            )
            if resp is None:
                return None
            phone = normalize_phone(resp.text)
            await safe_del(client, message.chat.id, [resp.id])
            if phone:
                break
            await message.reply("❌ <b>गलत नंबर फॉर्मेट!</b> दोबारा भेजें (+91...).")
        if not phone:
            return None

        # ── चरण 2: OTP ──
        try:
            sent = await user.send_code(phone)
        except FloodWait as e:
            await message.reply(
                f"⏳ टेलीग्राम ने कुछ देर के लिए रोका है। "
                f"<b>{e.value} सेकंड</b> बाद दोबारा /forward करें।"
            )
            return None
        except PhoneNumberInvalid:
            await message.reply("❌ <b>यह नंबर टेलीग्राम पर नहीं है।</b> /forward से दोबारा शुरू करें।")
            return None

        code = None
        for _ in range(CODE_RETRIES):
            resp = await ask(
                client, message,
                "🔑 <b>आपके नंबर पर OTP भेजा गया है — वह कोड यहाँ भेजें</b>",
            )
            if resp is None:
                return None
            code = normalize_otp(resp.text)
            await safe_del(client, message.chat.id, [resp.id])
            if code:
                break
            await message.reply("❌ <b>गलत OTP!</b> सिर्फ अंक भेजें (उदा: 12345).")
        if not code:
            return None

        try:
            me = await user.sign_in(phone, sent.phone_code_hash, code)
        except SessionPasswordNeeded:
            # ── चरण 3: 2FA पासवर्ड (अगर अकाउंट पर पासवर्ड लगा है) ──
            pw = None
            for _ in range(CODE_RETRIES):
                resp = await ask(
                    client, message,
                    "🔐 <b>इस अकाउंट पर टू-स्टेप (2FA) पासवर्ड लगा है</b>\n"
                    "पासवर्ड भेजें (यह मैसेज तुरंत डिलीट कर दिया जाएगा):",
                )
                if resp is None:
                    return None
                pw = normalize_password(resp.text)
                await safe_del(client, message.chat.id, [resp.id])
                if pw:
                    break
                await message.reply("❌ खाली पासवर्ड नहीं चलेगा — दोबारा भेजें।")
            if not pw:
                return None
            try:
                me = await user.check_password(pw)
            except PasswordHashInvalid:
                await message.reply("❌ <b>गलत 2FA पासवर्ड!</b> /forward से दोबारा शुरू करें।")
                return None
        except PhoneCodeInvalid:
            await message.reply("❌ <b>गलत/एक्सपायर्ड OTP!</b> /forward से दोबारा शुरू करें।")
            return None
        except PhoneCodeExpired:
            await message.reply("⌛ <b>OTP एक्सपायर हो गया।</b> /forward से दोबारा शुरू करें।")
            return None

        # ── सेशन सेव — अगली बार OTP नहीं माँगा जाएगा ──
        session = await _export_session(user)
        await db.save_forward_session(session, phone, getattr(me, "id", 0))
        _user_client = user
        await message.reply(
            "✅ <b>लॉगिन सफल!</b>\n"
            f"👤 अकाउंट: <code>{getattr(me, 'first_name', 'User')}</code>\n"
            f"📱 नंबर: <code>{mask_phone(phone)}</code>\n\n"
            "अब आगे डेस्टिनेशन और सोर्स चुनेंगे।"
        )
        return user

    except Exception as e:
        logger.error(f"Forward login failed: {e}")
        await message.reply(f"❌ <b>लॉगिन विफल:</b> <code>{e}</code>\nदोबारा /forward करें।")
        try:
            await user.disconnect()
        except Exception:
            pass
        return None


async def ensure_login(client, message):
    """पहले से लॉगिन है तो वही client, वरना login_conversation चलाओ"""
    user = await get_saved_client()
    if user:
        return user
    await message.reply(
        "🔐 <b>पहली बार लॉगिन ज़रूरी है</b>\n"
        "आपके टेलीग्राम अकाउंट से लॉगिन करके वीडियो भेजे जाएँगे "
        "(बिना फॉरवर्ड टैग)।\n\n"
        "नीचे स्टेप्स पूरे करें 👇"
    )
    return await login_conversation(client, message)


# ─────────────────────────────────────────────────
# 📤 STEP: डेस्टिनेशन चुनना + टेस्ट मैसेज चेक
# ─────────────────────────────────────────────────
async def ask_destination(client, message, user):
    """डेस्टिनेशन चैनल/ग्रुप ID लो → टेस्ट मैसेज भेजकर वेरीफाई करो।
    सफल होने पर chat-ref लौटाता है, वरना None."""
    state.phase = "dest"
    for _ in range(3):
        resp = await ask(
            client, message,
            "📤 <b>किस चैनल/ग्रुप में भेजना है?</b>\n"
            "उसका <b>ID</b> या <b>@username</b> भेजें\n"
            "(उदा: <code>-1001234567890</code> या <code>@mychannel</code>)",
            timeout=600,
        )
        if resp is None:
            return None
        dest = parse_chat_ref(resp.text)
        if dest is None:
            await message.reply("❌ <b>गलत फॉर्मेट!</b> ID या @username दोबारा भेजें।")
            continue

        # टेस्ट मैसेज — यही चेक करता है कि अकाउंट वहाँ पोस्ट कर सकता है या नहीं
        try:
            test = await user.send_message(
                dest,
                "✅ <b>Forward Test Message</b>\n\n"
                "यह टेस्ट मैसेज /forward कॉपी इंजन ने भेजा है। "
                "यह मिल गया मतलब डेस्टिनेशन सही है — आप इसे डिलीट कर सकते हैं।",
            )
            await message.reply(
                "✅ <b>टेस्ट मैसेज भेजा गया — डेस्टिनेशन सही है!</b>\n"
                f"📤 टारगेट: <code>{dest}</code>"
            )
            return dest
        except FloodWait as e:
            await message.reply(
                f"⏳ टेलीग्राम फ्लड-वेट: <b>{e.value} सेकंड</b> बाद दोबारा /forward करें।"
            )
            return None
        except Exception as e:
            await message.reply(
                f"❌ <b>टेस्ट मैसेज नहीं भेजा जा सका:</b> <code>{e}</code>\n\n"
                "सुनिश्चित करें कि लॉगिन अकाउंट उस चैनल/ग्रुप में है और पोस्ट कर सकता है।\n"
                "दूसरा ID भेजें 👇"
            )
    return None


# ─────────────────────────────────────────────────
# 📥 STEP: सोर्स चुनना + एडमिन चेक
# ─────────────────────────────────────────────────
async def ask_source(client, message, user):
    """सोर्स चैनल/ग्रुप ID लो → चेक करो लॉगिन यूज़र एडमिन है या नहीं।
    एडमिन हो तभी आगे बढ़ते हैं (पुराने मैसेज पढ़ने के लिए एडमिन ज़रूरी है)।
    सफल होने पर chat-ref लौटाता है, वरना None."""
    state.phase = "source"
    me = await user.get_me()

    for _ in range(3):
        resp = await ask(
            client, message,
            "📥 <b>किस चैनल/ग्रुप से वीडियो भेजने हैं?</b>\n"
            "उसका <b>ID</b> या <b>@username</b> भेजें",
            timeout=600,
        )
        if resp is None:
            return None
        src = parse_chat_ref(resp.text)
        if src is None:
            await message.reply("❌ <b>गलत फॉर्मेट!</b> ID या @username दोबारा भेजें।")
            continue

        # ── एडमिन चेक: लॉगिन यूज़र सोर्स में एडमिन है या नहीं ──
        try:
            member = await user.get_chat_member(src, me.id)
        except Exception as e:
            await message.reply(
                f"❌ <b>सोर्स एक्सेस नहीं हुआ:</b> <code>{e}</code>\n\n"
                "लॉगिन अकाउंट उस चैनल/ग्रुप का मेंबर/एडमिन होना चाहिए।\n"
                "दूसरा ID भेजें 👇"
            )
            continue

        status = getattr(member, "status", None)
        is_admin = status in (
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        )
        if not is_admin:
            await message.reply(
                "🛑 <b>एडमिन चेक फेल!</b>\n\n"
                f"👤 लॉगिन यूज़र: <code>{getattr(me, 'first_name', 'User')}</code>\n"
                f"📥 सोर्स: <code>{src}</code>\n"
                f"🔖 स्टेटस: <code>{status}</code>\n\n"
                "पुराने मैसेज पढ़ने के लिए लॉगिन यूज़र को उस सोर्स में "
                "<b>एडमिन/ओनर</b> होना चाहिए। एडमिन बनाकर दोबारा /forward करें।"
            )
            return None

        await message.reply(
            "✅ <b>एडमिन चेक पास!</b>\n"
            f"📥 सोर्स: <code>{src}</code>\n"
            f"👑 स्टेटस: <code>{status}</code>\n\n"
            "🚀 अब वीडियो कॉपी शुरू होगी…"
        )
        return src
    return None


# ─────────────────────────────────────────────────
# 📼 COPY ENGINE — बिना फॉरवर्ड टैग, सिर्फ वीडियो
# ─────────────────────────────────────────────────
async def send_without_forward_tag(user, msg, src, dest):
    """वीडियो को बिना 'Forwarded from' टैग के डेस्टिनेशन पर भेजता है।
    प्राइमरी: send_cached_media (नया मैसेज, वही मीडिया — कोई टैग नहीं)।
    फॉलबैक: raw ForwardMessages + drop_author=True (फॉरवर्ड हेडर हटता है)।"""
    file_id = msg.video.file_id if msg.video else msg.document.file_id

    # प्राइमरी — नया मैसेज के रूप में री-सेंड (caption + formatting बरकरार)
    try:
        return await user.send_cached_media(
            dest,
            file_id,
            caption=msg.caption or "",
            caption_entities=msg.caption_entities,
            parse_mode=enums.ParseMode.DISABLED,
        )
    except FloodWait:
        raise                            # ऊपर हैंडल होगा
    except Exception as e:
        logger.warning(f"send_cached_media failed (msg {msg.id}): {e}")

    # फॉलबैक — drop_author फॉरवर्ड (फॉरवर्ड टैग के बिना)
    try:
        return await user.invoke(
            raw.functions.messages.ForwardMessages(
                from_peer=await user.resolve_peer(src),
                to_peer=await user.resolve_peer(dest),
                id=[msg.id],
                random_id=[user.rnd_id()],
                drop_author=True,
            )
        )
    except FloodWait:
        raise
    except Exception as e:
        logger.error(f"drop_author forward also failed (msg {msg.id}): {e}")
        return None


async def run_copy_job(client, message, user, src, dest):
    """स्कैन → कॉपी लूप। पुराने→नई क्रम, हर फाइल के बीच 5-20s रैंडम गैप।"""
    state.phase = "send"
    status_msg = await message.reply("🔍 <b>सोर्स स्कैन हो रहा है…</b>")

    # ── फेज़ A: सिर्फ वीडियो फाइलों की ID इकट्ठी करो (पुराने→नई बाद में) ──
    video_ids, scanned = [], 0
    try:
        async for m in user.get_chat_history(src):
            if state.cancel:
                break
            scanned += 1
            if is_video_message(m):
                video_ids.append(m.id)
            if scanned % 2000 == 0:
                try:
                    await status_msg.edit(
                        f"🔍 <b>स्कैन जारी…</b>\n"
                        f"• मैसेज देखे: <code>{scanned}</code>\n"
                        f"• वीडियो मिले: <code>{len(video_ids)}</code>"
                    )
                except Exception:
                    pass
    except Exception as e:
        return await status_msg.edit(f"❌ <b>सोर्स स्कैन फेल:</b> <code>{e}</code>")

    if state.cancel:
        return await status_msg.edit("🛑 <b>/fstop — स्कैन बीच में रोका गया।</b>")

    video_ids.reverse()          # get_chat_history नई→पुरानी देता है; कॉपी पुराने→नई
    total = len(video_ids)
    if total == 0:
        return await status_msg.edit(
            f"🔍 <b>स्कैन पूरा!</b> कुल <code>{scanned}</code> मैसेज में "
            "कोई वीडियो फाइल नहीं मिली।"
        )

    await status_msg.edit(
        f"🚀 <b>कॉपी शुरू!</b>\n"
        f"• कुल वीडियो: <code>{total}</code>\n"
        f"• हर फाइल के बीच: <code>{SEND_GAP_MIN}-{SEND_GAP_MAX}s</code> रैंडम गैप\n"
        f"• रोकने के लिए: /fstop"
    )

    # ── फेज़ B: एक-एक करके भेजो (सिर्फ वीडियो, बिना टैग, रैंडम गैप) ──
    sent = failed = 0
    for idx, mid in enumerate(video_ids, 1):
        if state.cancel:
            break

        try:
            msg = await user.get_messages(src, mid)
            if not msg or msg.empty or not is_video_message(msg):
                continue

            result = await send_without_forward_tag(user, msg, src, dest)
            if result is None:
                failed += 1
            else:
                sent += 1

        except FloodWait as e:
            # फ्लड-वेट मिले तो वेट करके वही फाइल दोबारा
            wait = int(getattr(e, "value", 30)) + 1
            try:
                await status_msg.edit(
                    f"⏳ <b>फ्लड-वेट:</b> {wait}s रुककर आगे बढ़ेंगे… "
                    f"({idx}/{total})"
                )
            except Exception:
                pass
            await interruptible_sleep(wait)
            if state.cancel:
                break
            try:
                msg = await user.get_messages(src, mid)
                if msg and not msg.empty and is_video_message(msg):
                    result = await send_without_forward_tag(user, msg, src, dest)
                    if result is None:
                        failed += 1
                    else:
                        sent += 1
            except Exception as e2:
                failed += 1
                logger.error(f"Retry failed for {mid}: {e2}")

        except PeerFlood:
            await status_msg.edit(
                "🛑 <b>PeerFlood चेतावनी!</b>\n\n"
                "टेलीग्राम ने अकाउंट को फ्लड समझा है — बैन से बचने के लिए "
                "जॉब रोकी गई। कुछ घंटे बाद /forward दोबारा चलाएँ।"
            )
            return

        except Exception as e:
            failed += 1
            logger.error(f"Copy failed for msg {mid}: {e}")

        # प्रोग्रेस अपडेट + रैंडम 5-20s गैप (स्पैम/बैन सेफ)
        gap = random_gap()
        try:
            await status_msg.edit(
                f"📤 <b>वीडियो भेजे जा रहे हैं…</b>\n"
                f"• प्रगति: <code>{idx}/{total}</code>\n"
                f"• ✅ भेजे: <code>{sent}</code> | ❌ फेल: <code>{failed}</code>\n"
                f"• ⏱️ अगली फाइल: <code>{gap}s</code> बाद\n"
                f"• रोकने के लिए: /fstop"
            )
        except Exception:
            pass
        await interruptible_sleep(gap)

    # ── फाइनल रिपोर्ट ──
    stopped = " (बीच में रोका गया — /fstop)" if state.cancel else ""
    await message.reply(
        f"🏁 <b>कॉपी जॉब पूरी हुई{stopped}</b>\n\n"
        f"📥 सोर्स: <code>{src}</code>\n"
        f"📤 डेस्टिनेशन: <code>{dest}</code>\n"
        f"• कुल वीडियो मिले: <code>{total}</code>\n"
        f"• ✅ सफल भेजे: <code>{sent}</code>\n"
        f"• ❌ विफल: <code>{failed}</code>"
    )


# ─────────────────────────────────────────────────
# 🎯 MAIN COMMAND: /forward
# ─────────────────────────────────────────────────
@Client.on_message(filters.command(["forward", "fwd"]) & filters.user(ADMINS))
async def forward_cmd(client, message):
    # सिर्फ PM — फोन/OTP/पासवर्ड जैसा सेंसिटिव डेटा ग्रुप में नहीं
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply(
            "🔒 <b>यह कमांड सिर्फ PM में काम करती है</b>\n"
            "बॉट को पर्सनल चैट में /forward भेजें।"
        )

    arg = message.command[1].lower() if len(message.command) > 1 else ""

    # ── /forward logout — सेव यूज़र लॉगिन हटाओ ──
    if arg == "logout":
        global _user_client
        if _user_client:
            try:
                await _user_client.disconnect()
            except Exception:
                pass
            _user_client = None
        await db.clear_forward_session()
        return await message.reply(
            "🗑️ <b>यूज़र लॉगिन हटा दिया गया।</b>\n"
            "अगली बार /forward पर दोबारा नंबर + OTP माँगा जाएगा।"
        )

    # ── /forward stop — चलती जॉब रोको ──
    if arg in ("stop", "cancel"):
        if state.busy:
            state.cancel = True
            return await message.reply("🛑 <b>जॉब रोकने का सिग्नल भेजा गया…</b>")
        return await message.reply("ℹ️ कोई जॉब नहीं चल रही।")

    # ── /forward status — स्टेटस दिखाओ ──
    if arg == "status":
        rec = await db.get_forward_session()
        login_txt = (
            f"✅ लॉगिन: <code>{mask_phone(rec.get('phone'))}</code>"
            if rec else "❌ लॉगिन नहीं (पहली बार /forward चलाएँ)"
        )
        job_txt = (
            f"▶️ चल रही है (फेज़: <code>{state.phase}</code>)"
            if state.busy else "⏹️ कोई जॉब नहीं"
        )
        return await message.reply(
            f"📊 <b>/forward स्टेटस</b>\n\n"
            f"🔐 {login_txt}\n"
            f"⚙️ जॉब: {job_txt}\n"
            f"⏱️ गैप: <code>{SEND_GAP_MIN}-{SEND_GAP_MAX}s</code> / फाइल"
        )

    # ── नई जॉब गार्ड — एक समय में सिर्फ एक फ्लो ──
    if state.busy:
        return await message.reply(
            "⚠️ <b>एक /forward फ्लो पहले से चल रही है!</b>\n"
            "रोकना है तो /fstop भेजें।"
        )

    state.busy = True
    state.cancel = False
    state.phase = "login"
    try:
        # 1) लॉगिन (पहली बार: नंबर → OTP → 2FA; बाद में: सेव सेशन)
        user = await ensure_login(client, message)
        if user is None:
            return
        await warm_peer_cache(user)

        # 2) डेस्टिनेशन चैनल/ग्रुप → टेस्ट मैसेज चेक
        dest = await ask_destination(client, message, user)
        if dest is None:
            return

        # 3) सोर्स चैनल/ग्रुप → एडमिन चेक
        src = await ask_source(client, message, user)
        if src is None:
            return

        # 4) एडमिन चेक पास → अब सेंड होने लगेगा
        await run_copy_job(client, message, user, src, dest)

    finally:
        state.busy = False
        state.cancel = False
        state.phase = ""


# ─────────────────────────────────────────────────
# 🛑 /fstop — चलती हुई कॉपी जॉब रोकें
# ─────────────────────────────────────────────────
@Client.on_message(filters.command(["fstop"]) & filters.user(ADMINS))
async def fstop_cmd(client, message):
    if state.busy:
        state.cancel = True
        await message.reply("🛑 <b>रोकने का सिग्नल भेजा गया — जॉब जल्द रुक जाएगी।</b>")
    else:
        await message.reply("ℹ️ <b>कोई /forward जॉब नहीं चल रही।</b>")
