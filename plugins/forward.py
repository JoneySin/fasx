"""
🎬 /forward COMMAND FLOW (केवल ADMINS, केवल PM)

Commands:
  /forward     → setup शुरू (Destination → Source → Summary → ✅ Start)
  /stopforward → चल रहे job को सुरक्षित रूप से रोकना (checkpoint सेव रहता है)
  /cancel      → केवल वर्तमान setup रद्द करना (चल रहा job नहीं रुकता)

Routing notes (Hydrogram 0.2.0 में सभी matching handlers चलते हैं, group में break नहीं होता):
- Setup के दौरान admin के text/forward input को group -2 में StopPropagation से रोका जाता है,
  ताकि pm_search / auto_index उसी ID को search या index न करें।
- /cancel group -2 में है पर StopPropagation नहीं करता, ताकि check_db_TEMP का /cancel भी चले।
"""

import asyncio
import html
import logging
import re
import time

from hydrogram import Client, StopPropagation, filters
from hydrogram.errors import FloodWait
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from info import ADMINS, FORWARD_ENABLED
from forward_service import (
    DEFAULT_MEDIA_TYPES,
    MEDIA_OPTIONS,
    ForwardError,
    ForwardJob,
    ValidationError,
    check_destination,
    check_source,
    ensure_distinct_chats,
    get_active_job,
    get_forward_store,
    job_from_doc,
    launch_job,
    parse_chat_ref,
    request_stop,
    resume_block_reason,
    RESUMABLE_STATUSES,
    get_copy_delay_range,
)
from user_client import (
    LOGIN_PHONE_PROMPT,
    UserSessionError,
    begin_login,
    cancel_login,
    ensure_user_client,
    get_user_client,
    is_login_active,
    submit_login_code,
    submit_login_password,
)

logger = logging.getLogger(__name__)

# FORWARD_ENABLED=false होने पर हर forward handler का filter False → कोई जवाब नहीं, कोई काम नहीं
FEATURE_ON = filters.create(lambda _, __, ___: bool(FORWARD_ENABLED), name="ForwardEnabled")
ADMIN_PM = FEATURE_ON & filters.private & filters.user(ADMINS)

# admin_id -> setup state (in-memory; restart पर खत्म — resume के लिए ForwardJobs में checkpoint है)
SETUP = {}
SETUP_TTL = 900  # 15 मिनट में setup अपने-आप expire


def _set_setup(uid, step):
    st = SETUP.get(uid) or {"dst": None, "src": None}
    st.update(step=step, ts=time.time())
    SETUP[uid] = st
    return st


LOGIN_STEPS = ("login_phone", "login_otp", "login_pwd")


def _drop_setup(uid):
    """Setup हटाता है; login चल रहा हो तो उसका temporary client भी बंद करता है।"""
    st = SETUP.pop(uid, None)
    if st and st.get("step") in LOGIN_STEPS:
        asyncio.create_task(cancel_login())
    return st


def _get_setup(uid):
    st = SETUP.get(uid)
    if not st:
        return None
    if time.time() - st["ts"] > SETUP_TTL:
        _drop_setup(uid)
        return None
    st["ts"] = time.time()
    return st


def _media_labels(types):
    return ", ".join(MEDIA_OPTIONS[t] for t in MEDIA_OPTIONS if t in types) or "कुछ नहीं"


def _media_panel_text(types):
    return (
        "🎛 <b>Step 3/3 — क्या-क्या फ़ॉरवर्ड करना है?</b>\n\n"
        "नीचे बटन दबाकर चुनें (✅ = चुना हुआ)। कम से कम एक चुनना होगा।\n"
        f"चुना हुआ: <b>{html.escape(_media_labels(types))}</b>\n\n"
        "Message नए मैसेज की तरह कॉपी होंगे (forward tag नहीं)। "
        "Text-only messages कभी कॉपी नहीं होते।"
    )


def _media_markup(types):
    rows = []
    for key, label in MEDIA_OPTIONS.items():
        mark = "✅" if key in types else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {label}", callback_data=f"fwd#m#{key}")])
    rows.append([
        InlineKeyboardButton("➡️ आगे (Summary)", callback_data="fwd#mdone"),
        InlineKeyboardButton("❌ Cancel", callback_data="fwd#cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _summary_text(dst, src, types=DEFAULT_MEDIA_TYPES):
    lo, hi = get_copy_delay_range()
    return (
        "🧾 <b>Forward Summary</b>\n\n"
        f"📤 <b>Source:</b> {html.escape(src.title)} <code>{src.chat_id}</code>\n"
        f"   └ {html.escape(src.note) if src.note else 'सदस्यता जाँची गई'}\n"
        f"📥 <b>Destination:</b> {html.escape(dst.title)} <code>{dst.chat_id}</code>\n\n"
        f"🎞️ Media: <b>{html.escape(_media_labels(types))}</b> (बाकी types छोड़े जाएँगे)\n"
        "📋 Mode: नया message (forward attribution नहीं), caption और original quality सुरक्षित\n"
        "🔎 Scan: पुराने से नए की ओर, batch में\n"
        f"⏱️ Delay: हर सफल copy के बाद {lo}–{hi} सेकंड (random)\n\n"
        "⚠️ Telegram के rate limits/ban से सुरक्षा की गारंटी नहीं दी जा सकती। "
        "FloodWait आने पर job अपने-आप रुककर समय बताएगा।\n\n"
        "शुरू करें?"
    )


def _confirm_markup():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Start", callback_data="fwd#start"),
            InlineKeyboardButton("❌ Cancel", callback_data="fwd#cancel"),
        ]
    ])


# ─────────────────────────────────────────────
# /forward
# ─────────────────────────────────────────────
@Client.on_message(filters.command("forward") & ADMIN_PM)
async def forward_cmd(client, message):
    if get_active_job() is not None:
        return await message.reply("⚠️ एक forward job पहले से चल रहा है। पहले /stopforward भेजें।")

    try:
        await ensure_user_client()
    except UserSessionError as e:
        if e.needs_login:
            _set_setup(message.from_user.id, "login_phone")
            return await message.reply(LOGIN_PHONE_PROMPT)
        return await message.reply(str(e))

    resume_buttons = []
    try:
        rows = await get_forward_store().find_resumable_jobs(RESUMABLE_STATUSES, limit=3)
        for row in rows:
            label = f"▶️ Resume: {row.get('src_title', '')[:18] or row['src_id']} → {row.get('dst_title', '')[:18] or row['dst_id']}"
            resume_buttons.append([InlineKeyboardButton(label, callback_data=f"fwd#resume#{row['_id']}")])
    except Exception as e:
        logger.warning(f"resumable job lookup failed: {type(e).__name__}")

    _set_setup(message.from_user.id, "dest")
    text = (
        "🎬 <b>Video Copy Setup</b> — Step 1/2\n\n"
        "Destination group/channel भेजें:\n"
        "• Chat ID (जैसे <code>-1001234567890</code>)\n"
        "• @username या t.me link\n"
        "• या उस chat का कोई message forward करें\n\n"
        "User account को destination में message भेजने की permission होनी चाहिए।\n"
        "रद्द करने के लिए /cancel"
    )
    if resume_buttons:
        text += "\n\n♻️ पिछला अधूरा job जारी करना चाहें तो नीचे चुनें:"
    markup = InlineKeyboardMarkup(resume_buttons) if resume_buttons else None
    await message.reply(text, reply_markup=markup)


# ─────────────────────────────────────────────
# SETUP INPUT (group -2, admin-only, setup active होने पर ही)
# ─────────────────────────────────────────────
async def _handle_login_input(message, state):
    """Login के तीन steps: phone → OTP → (2FA password). OTP/password सेव नहीं होते।"""
    uid = message.from_user.id
    step = state["step"]
    text = (message.text or "").strip()

    if step in ("login_otp", "login_pwd"):
        # संवेदनशील संदेश हटाने की कोशिश (bot सकारात्मक न हो तो चुपचाप आगे बढ़ें)
        try:
            await message.delete()
        except Exception:
            pass

    try:
        if step == "login_phone":
            await begin_login(text)
            _set_setup(uid, "login_otp")
            reply = (
                "📨 Telegram ने OTP भेज दिया है (उसी account के app/SMS में देखें)।\n\n"
                "<b>Step 2/2:</b> OTP यहाँ भेजें (जैसे <code>12345</code>)।\n"
                "⚠️ OTP इसी chat में दिखेगा — login के बाद उस message को delete कर दें।\n"
                "रद्द करने के लिए /cancel"
            )
        elif step == "login_otp":
            code = re.sub(r"[\s\-]", "", text)
            if not code.isdigit():
                await message.reply("❌ OTP केवल अंकों में भेजें (जैसे 12345)। या /cancel।")
                return
            if await submit_login_code(code):
                _set_setup(uid, "dest")
                reply = LOGIN_DONE_TEXT
            else:
                _set_setup(uid, "login_pwd")
                reply = (
                    "🔑 इस account पर 2FA password सेट है।\n"
                    "2FA password भेजें (संदेश तुरंत delete करने की कोशिश होगी)।\n"
                    "रद्द करने के लिए /cancel"
                )
        else:  # login_pwd
            await submit_login_password(text)
            _set_setup(uid, "dest")
            reply = LOGIN_DONE_TEXT
    except UserSessionError as e:
        if not is_login_active():
            SETUP.pop(uid, None)
        reply = f"{e}\n\n" + ("" if not is_login_active() else "दोबारा भेजें, या /cancel")
    except Exception as e:
        logger.error(f"login step failed: {type(e).__name__}")
        await cancel_login()
        SETUP.pop(uid, None)
        reply = "❌ Login में अनपेक्षित त्रुटि हुई। /forward से फिर शुरू करें।"

    await message.reply(reply)


LOGIN_DONE_TEXT = (
    "✅ <b>User account login सफल!</b> Session सेव हो गया है — अगली बार OTP नहीं माँगा जाएगा।\n\n"
    "🎬 <b>Step 1/2</b> — Destination group/channel भेजें (ID, @username, t.me link, या message forward)।"
)


def _ref_from_message(message):
    fwd_chat = getattr(message, "forward_from_chat", None)
    if fwd_chat is not None:
        return fwd_chat.id
    if message.text:
        return parse_chat_ref(message.text)
    raise ValidationError("Chat ID, @username, t.me link या किसी chat का message forward करें।")


@Client.on_message(
    ADMIN_PM & (filters.text | filters.forwarded) & ~filters.command(["forward", "stopforward", "cancel"]),
    group=-2,
)
async def forward_setup_input(client, message):
    state = _get_setup(message.from_user.id)
    if not state:
        return  # setup नहीं — बाकी handlers सामान्य रूप से चलें

    if state["step"] == "confirm":
        await message.reply("⬆️ Summary के नीचे ✅ Start या ❌ Cancel दबाएँ, या /cancel भेजें।")
        raise StopPropagation

    if state["step"] in LOGIN_STEPS:
        await _handle_login_input(message, state)
        raise StopPropagation

    if state["step"] == "media":
        await message.reply("⬆️ ऊपर के बटनों से media types चुनें, फिर ➡️ आगे दबाएँ, या /cancel भेजें।")
        raise StopPropagation

    user = get_user_client()
    if user is None:
        try:
            user = await ensure_user_client()
        except UserSessionError as e:
            if e.needs_login:
                _set_setup(message.from_user.id, "login_phone")
                await message.reply(LOGIN_PHONE_PROMPT)
            else:
                await message.reply(str(e))
            raise StopPropagation

    status_msg = await message.reply("⏳ User account से जाँच हो रही है…")
    markup = None
    try:
        ref = _ref_from_message(message)
        if state["step"] == "dest":
            dst = await check_destination(user, ref)
            state["dst"] = dst
            _set_setup(message.from_user.id, "source")
            text = (
                f"✅ Destination ठीक है: <b>{html.escape(dst.title)}</b> <code>{dst.chat_id}</code>\n\n"
                "🎬 <b>Step 2/2</b> — Source group/channel भेजें (ID, @username, t.me link, या message forward)।"
            )
        else:
            src = await check_source(user, ref)
            ensure_distinct_chats(src.chat_id, state["dst"].chat_id)
            state["src"] = src
            state["media"] = list(DEFAULT_MEDIA_TYPES)
            _set_setup(message.from_user.id, "media")
            text = _media_panel_text(state["media"])
            markup = _media_markup(state["media"])
    except ValidationError as e:
        text = f"❌ {e}\n\nसही जानकारी दोबारा भेजें, या /cancel"
    except FloodWait as e:
        text = f"⏳ Telegram ने {e.value} सेकंड प्रतीक्षा माँगी है। थोड़ी देर बाद दोबारा प्रयास करें।"
    except Exception as e:
        logger.error(f"forward setup check failed: {type(e).__name__}")
        text = "❌ जाँच के दौरान अनपेक्षित त्रुटि हुई। दोबारा प्रयास करें या /cancel।"

    try:
        await status_msg.edit(text, reply_markup=markup)
    except Exception:
        await message.reply(text, reply_markup=markup)
    raise StopPropagation


# ─────────────────────────────────────────────
# /cancel — केवल setup; group -2 में, बिना StopPropagation (check_db का /cancel भी चले)
# ─────────────────────────────────────────────
@Client.on_message(filters.command("cancel") & ADMIN_PM, group=-2)
async def forward_cancel_cmd(client, message):
    if _drop_setup(message.from_user.id) is not None:
        await message.reply("❌ Setup/login रद्द कर दिया गया। (चल रहा job, यदि कोई है, तो /stopforward से रुकेगा)")


# ─────────────────────────────────────────────
# /stopforward
# ─────────────────────────────────────────────
@Client.on_message(filters.command("stopforward") & ADMIN_PM)
async def stop_forward_cmd(client, message):
    job = request_stop()
    if job is None:
        return await message.reply("ℹ️ इस समय कोई forward job नहीं चल रहा।")
    await message.reply(
        "⏹ Stop अनुरोध भेजा गया। वर्तमान copy पूरा होकर job सुरक्षित रूप से रुक जाएगा और "
        "checkpoint सेव रहेगा (बाद में /forward → ▶️ Resume)।"
    )


# ─────────────────────────────────────────────
# CALLBACKS (सभी admin-only)
# ─────────────────────────────────────────────
@Client.on_callback_query(FEATURE_ON & filters.regex(r"^fwd#"))
async def forward_callbacks(client, query):
    if query.from_user is None or query.from_user.id not in ADMINS:
        return await query.answer("⛔ यह केवल admin के लिए है।", show_alert=True)

    parts = query.data.split("#")
    action = parts[1] if len(parts) > 1 else ""
    uid = query.from_user.id

    if action == "stop":
        job = request_stop()
        if job is None:
            return await query.answer("कोई job नहीं चल रहा।", show_alert=True)
        return await query.answer("⏹ Stop अनुरोध भेजा गया।")

    if action == "cancel":
        _drop_setup(uid)
        await query.answer("रद्द किया गया।")
        try:
            await query.message.edit("❌ Forward setup रद्द कर दिया गया।")
        except Exception:
            pass
        return

    if action == "start":
        return await _start_from_setup(client, query)

    if action == "m" and len(parts) == 3:
        return await _toggle_media(query, uid, parts[2])

    if action == "mdone":
        return await _media_done(query, uid)

    if action == "resume" and len(parts) == 3:
        return await _resume(client, query, parts[2])

    await query.answer("अज्ञात action।", show_alert=True)


async def _toggle_media(query, uid, key):
    state = _get_setup(uid)
    if not state or state.get("step") != "media" or key not in MEDIA_OPTIONS:
        return await query.answer("Setup नहीं मिला या expire हो गया। /forward से फिर शुरू करें।", show_alert=True)
    types = list(state.get("media") or [])
    if key in types:
        types.remove(key)
    else:
        types.append(key)
    state["media"] = types
    await query.answer("✅ अपडेट" if key in types else "⬜ हटाया")
    try:
        await query.message.edit(_media_panel_text(types), reply_markup=_media_markup(types))
    except Exception:
        pass


async def _media_done(query, uid):
    state = _get_setup(uid)
    if not state or state.get("step") != "media":
        return await query.answer("Setup नहीं मिला या expire हो गया। /forward से फिर शुरू करें।", show_alert=True)
    types = [t for t in MEDIA_OPTIONS if t in (state.get("media") or [])]
    if not types:
        return await query.answer("कम से कम एक media type चुनें।", show_alert=True)
    state["media"] = types
    _set_setup(uid, "confirm")
    await query.answer()
    try:
        await query.message.edit(_summary_text(state["dst"], state["src"], types), reply_markup=_confirm_markup())
    except Exception:
        pass


async def _start_from_setup(client, query):
    uid = query.from_user.id
    state = _get_setup(uid)
    if not state or state.get("step") != "confirm" or not state.get("src") or not state.get("dst"):
        return await query.answer("Setup नहीं मिला या expire हो गया। /forward से फिर शुरू करें।", show_alert=True)
    if get_active_job() is not None:
        return await query.answer("एक job पहले से चल रहा है।", show_alert=True)

    try:
        user = await ensure_user_client()
    except UserSessionError:
        return await query.answer("User session उपलब्ध नहीं। विवरण के लिए /forward संदेश देखें।", show_alert=True)

    dst, src = state["dst"], state["src"]
    job = ForwardJob(
        admin_id=uid,
        src_id=src.chat_id,
        dst_id=dst.chat_id,
        src_title=src.title,
        dst_title=dst.title,
        media_types=tuple(t for t in MEDIA_OPTIONS if t in (state.get("media") or [])) or DEFAULT_MEDIA_TYPES,
    )
    try:
        await launch_job(client, job, user)
    except ForwardError as e:
        return await query.answer(str(e), show_alert=True)
    except Exception as e:
        logger.error(f"forward launch failed: {type(e).__name__}")
        return await query.answer("Job शुरू नहीं हो सका (database/Telegram जाँचें)।", show_alert=True)

    SETUP.pop(uid, None)
    await query.answer("✅ Job शुरू हुआ")
    try:
        await query.message.edit("✅ Job शुरू हो गया — progress नीचे अलग संदेश में दिख रहा है।")
    except Exception:
        pass


async def _resume(client, query, job_id):
    uid = query.from_user.id
    store = get_forward_store()
    doc = await store.get_job(job_id)
    if not doc:
        return await query.answer("यह job नहीं मिला।", show_alert=True)

    job = job_from_doc(doc)
    reason = resume_block_reason(job, time.time())
    if reason:
        return await query.answer(reason, show_alert=True)
    if get_active_job() is not None:
        return await query.answer("एक job पहले से चल रहा है।", show_alert=True)

    try:
        user = await ensure_user_client()
    except UserSessionError:
        return await query.answer("User session उपलब्ध नहीं। विवरण के लिए /forward संदेश देखें।", show_alert=True)

    # Resume से पहले access फिर से जाँचें (permissions बदल सकती हैं)
    try:
        src = await check_source(user, job.src_id)
        dst = await check_destination(user, job.dst_id)
        ensure_distinct_chats(src.chat_id, dst.chat_id)
    except ForwardError as e:
        return await query.answer(str(e), show_alert=True)
    except FloodWait as e:
        return await query.answer(f"Telegram FloodWait: {e.value} सेकंड।", show_alert=True)

    job.admin_id = uid
    job.src_title, job.dst_title = src.title, dst.title
    job.status = "pending"
    try:
        await launch_job(client, job, user, store)
    except ForwardError as e:
        return await query.answer(str(e), show_alert=True)

    await query.answer("▶️ Resume शुरू हुआ")
    try:
        await query.message.edit("▶️ Job resume हो गया — progress नीचे अलग संदेश में दिख रहा है।")
    except Exception:
        pass
