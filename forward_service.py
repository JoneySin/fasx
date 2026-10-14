"""
🎬 /forward — Telegram USER account से पुराने ग्रुप/चैनल के VIDEO नए मैसेज की तरह copy करने का engine.

नियम (जो इस फ़ाइल में लागू होते हैं):
- सभी read/copy operations User Client से होते हैं; progress/alerts Bot Client से (plugins/forward.py).
- केवल video media: Telegram `video` या `video/*` MIME वाला document। केवल filename से कुछ तय नहीं होता।
- `copy_message` → नया मैसेज (forward attribution नहीं), caption और original file सुरक्षित।
- हर सफल copy के बाद FORWARD_DELAY_MIN..MAX (default 5–20 सेकंड, random) का विराम।
- FloodWait / SlowmodeWait → job रुक जाता है, कोई auto-retry नहीं (Telegram की सीमा का सम्मान)।
- Network errors → सीमित retries (NETWORK_BACKOFF), फिर job resumable state में।
- Duplicate tracking: `ForwardCopied` में (src_id, dst_id, src_msg_id) unique।
- Source messages को 200-200 IDs के batch में ascending क्रम में स्कैन किया जाता है;
  सारे message IDs RAM में इकट्ठा नहीं किए जाते।
"""

import asyncio
import html
import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

import pytz
from hydrogram import enums
from hydrogram.errors import (
    AuthKeyInvalid,
    AuthKeyUnregistered,
    ChannelInvalid,
    ChannelPrivate,
    ChatAdminRequired,
    ChatForwardsRestricted,
    ChatInvalid,
    ChatRestricted,
    ChatWriteForbidden,
    FloodWait,
    MessageIdInvalid,
    MsgIdInvalid,
    PeerIdInvalid,
    RPCError,
    SessionExpired,
    SessionRevoked,
    SlowmodeWait,
    UserBannedInChannel,
    UserDeactivated,
    UserNotParticipant,
    UserRestricted,
    UsernameInvalid,
    UsernameNotOccupied,
)
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from info import FORWARD_DELAY_MIN, FORWARD_DELAY_MAX, TIME_ZONE
from database.users_chats_db import db as main_db
from user_client import warm_peer_cache

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ⚙️ TUNABLES
# ─────────────────────────────────────────────
SCAN_BATCH = 200                 # एक get_messages call में अधिकतम IDs (Telegram limit)
NETWORK_BACKOFF = (5, 15, 30)    # network error पर इतने प्रयास, फिर job रुकता है
MAX_CONSECUTIVE_FAILURES = 10    # लगातार इतनी per-message failures → job रोका जाता है
PROGRESS_INTERVAL = 10           # progress message edit का न्यूनतम अंतराल (सेकंड)
DELAY_FLOOR = 5                  # हर सफल copy के बाद का न्यूनतम विराम (सेकंड)
DELAY_CEIL = 20                  # अधिकतम विराम (सेकंड)
RESUMABLE_STATUSES = ("interrupted", "stopped", "floodwait", "error")

NETWORK_ERRORS = (ConnectionError, TimeoutError, OSError)

# Job को रोक देने वाले (access/permission) errors
STOP_ERRORS = (
    ChatWriteForbidden,
    ChatAdminRequired,
    ChatRestricted,
    UserBannedInChannel,
    UserRestricted,
    UserNotParticipant,
    ChannelPrivate,
    ChannelInvalid,
    ChatInvalid,
    PeerIdInvalid,
    AuthKeyInvalid,
    AuthKeyUnregistered,
    SessionExpired,
    SessionRevoked,
    UserDeactivated,
)

# केवल उस एक message को skip करने वाले errors
MESSAGE_SKIP_ERRORS = (
    ChatForwardsRestricted,
    MessageIdInvalid,
    MsgIdInvalid,
)

ERROR_HINTS = (
    (ChatWriteForbidden, "Destination में message भेजने की permission नहीं है।"),
    (ChatAdminRequired, "Admin अधिकार की ज़रूरत है (chat में)।"),
    (ChatRestricted, "User account इस chat में restricted है।"),
    (UserBannedInChannel, "User account इस channel में ban है।"),
    (UserRestricted, "User account पर Telegram restriction है।"),
    (UserNotParticipant, "User account इस chat का member नहीं है।"),
    (ChannelPrivate, "Chat private है या User account की access नहीं है।"),
    (ChannelInvalid, "Chat ID अमान्य है या chat उपलब्ध नहीं है।"),
    (ChatInvalid, "Chat अमान्य है या उपलब्ध नहीं है।"),
    (PeerIdInvalid, "Chat पहचाना नहीं जा सका (ID/access जाँचें)।"),
    (ChatForwardsRestricted, "इस message को copy करने की अनुमति नहीं (restricted content)।"),
    (AuthKeyInvalid, "User session invalid है — नया USER_SESSION_STRING बनाएँ।"),
    (AuthKeyUnregistered, "User session invalid है — नया USER_SESSION_STRING बनाएँ।"),
    (SessionExpired, "User session expire हो चुका है — नया USER_SESSION_STRING बनाएँ।"),
    (SessionRevoked, "User session revoke हो चुका है — नया USER_SESSION_STRING बनाएँ।"),
    (UserDeactivated, "User account deactivate है।"),
)

STATUS_TEXT = {
    "pending": "⏳ Pending",
    "running": "▶️ Running",
    "stopped": "⏹ Stopped (admin ने रोका — /forward → Resume से जारी करें)",
    "floodwait": "⏳ FloodWait — job रुका (नीचे दिया समय बीतने के बाद Resume करें)",
    "completed": "✅ Completed",
    "interrupted": "⚠️ Interrupted (bot restart/shutdown) — Resume उपलब्ध",
    "error": "❌ Error — job रुका (Resume उपलब्ध हो सकता है)",
}


class ForwardError(Exception):
    """User-facing error (Hindi message, कोई secret नहीं)।"""


class ValidationError(ForwardError):
    """Destination/Source validation की विफलता।"""


# ─────────────────────────────────────────────
# 🔐 ADMIN CHECK (हर handler इसी से जाँचता है)
# ─────────────────────────────────────────────
def is_admin(user_id, admins) -> bool:
    try:
        return user_id is not None and int(user_id) in set(int(a) for a in admins)
    except (TypeError, ValueError):
        return False


# ─────────────────────────────────────────────
# 🎞️ VIDEO FILTER (pure, testable)
# ─────────────────────────────────────────────
def is_forwardable_video(message) -> bool:
    """केवल वास्तविक video media → True।
    - Telegram native video → True
    - Document जिसका MIME `video/*` है → True
    - Photo, audio, voice, PDF, ZIP, GIF/animation, video note, sticker आदि → False
    - Filename (.mp4 आदि) देखकर कभी video नहीं मानते।
    """
    if message is None or getattr(message, "empty", False):
        return False
    if getattr(message, "animation", None) or getattr(message, "video_note", None):
        return False
    if getattr(message, "video", None):
        return True
    doc = getattr(message, "document", None)
    if doc is not None:
        mime = (getattr(doc, "mime_type", None) or "").strip().lower()
        return mime.startswith("video/")
    return False


# ─────────────────────────────────────────────
# ⏱️ DELAY (pure, testable)
# ─────────────────────────────────────────────
def get_copy_delay_range():
    """FORWARD_DELAY_MIN/MAX को 5–20 सेकंड की सीमा में clamp करता है।"""
    lo = min(max(int(FORWARD_DELAY_MIN), DELAY_FLOOR), DELAY_CEIL)
    hi = min(max(int(FORWARD_DELAY_MAX), DELAY_FLOOR), DELAY_CEIL)
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def random_copy_delay() -> float:
    lo, hi = get_copy_delay_range()
    return random.uniform(lo, hi)


# ─────────────────────────────────────────────
# 🔤 CHAT REFERENCE PARSER (pure, testable)
# ─────────────────────────────────────────────
_TME_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?t\.me/(?:c/(\d+)|([A-Za-z][A-Za-z0-9_]{3,}))(?:/\d+)?/?$"
)


def parse_chat_ref(text: str):
    """Chat ID (-100…), @username, या t.me link → int या '@username'।"""
    t = (text or "").strip()
    if not t:
        raise ValidationError("Chat ID, @username या t.me link खाली है।")
    m = _TME_RE.match(t)
    if m:
        if m.group(1):
            return int(f"-100{m.group(1)}")
        return "@" + m.group(2)
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{3,}", t):
        return "@" + t.lstrip("@")
    raise ValidationError(
        "यह valid Chat ID/username/t.me link नहीं लगता। उदाहरण: <code>-1001234567890</code> या <code>@channelname</code>।"
    )


def ensure_distinct_chats(src_id, dst_id) -> None:
    if int(src_id) == int(dst_id):
        raise ValidationError("Source और Destination समान नहीं हो सकते। अलग chat चुनें।")


# ─────────────────────────────────────────────
# 🚦 ERROR CLASSIFICATION (pure, testable)
# ─────────────────────────────────────────────
def classify_error(exc) -> str:
    """'rate_limit' | 'stop' | 'network' | 'skip'"""
    if isinstance(exc, (FloodWait, SlowmodeWait)):
        return "rate_limit"
    if isinstance(exc, STOP_ERRORS):
        return "stop"
    if isinstance(exc, NETWORK_ERRORS):
        return "network"
    if isinstance(exc, MESSAGE_SKIP_ERRORS):
        return "skip"
    if isinstance(exc, RPCError):
        return "skip"
    return "stop"


def describe_error(exc) -> str:
    for cls, hint in ERROR_HINTS:
        if isinstance(exc, cls):
            return hint
    if isinstance(exc, NETWORK_ERRORS):
        return "Network समस्या — कुछ देर बाद Resume करें।"
    return f"Unexpected error: {type(exc).__name__}"


# ─────────────────────────────────────────────
# 🔍 DESTINATION / SOURCE VALIDATION
# ─────────────────────────────────────────────
@dataclass
class ChatInfo:
    chat_id: int
    title: str
    kind: str          # enums.ChatType का नाम: CHANNEL / GROUP / SUPERGROUP
    note: str = ""     # जैसे "सदस्य नहीं (public read)"


def _ensure_group_or_channel(chat):
    if chat.type not in (enums.ChatType.CHANNEL, enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        raise ValidationError("केवल group, supergroup या channel चुना जा सकता है (private chat/bot नहीं)।")


def destination_permission_error(chat_type, status, privileges, member_permissions, chat_permissions):
    """Pure check: post/send करने की वास्तविक permission। समस्या हो तो Hindi message, वरना None।"""
    S = enums.ChatMemberStatus
    if status in (S.LEFT, S.BANNED):
        return "User account इस destination का member नहीं है या ban है। पहले उसे join/add करें।"

    if chat_type == enums.ChatType.CHANNEL:
        if status == S.OWNER:
            return None
        if status == S.ADMINISTRATOR and privileges is not None and getattr(privileges, "can_post_messages", False):
            return None
        return "Channel में User account के पास Post Messages की admin permission नहीं है।"

    # group / supergroup
    if status in (S.OWNER, S.ADMINISTRATOR):
        return None
    if status == S.RESTRICTED:
        perms = member_permissions
    elif status == S.MEMBER:
        perms = chat_permissions
    else:
        return "User account के पास इस group में send permission नहीं है।"
    if perms is not None and getattr(perms, "can_send_media_messages", True) is False:
        return "इस group में User account के लिए media (video) भेजने की permission बंद है।"
    return None


async def latest_message_id(user, chat_id) -> int:
    async for msg in user.get_chat_history(chat_id, limit=1):
        return int(msg.id)
    return 0


async def resolve_chat(user, ref):
    """get_chat with एक बार dialogs-cache fallback (restart के बाद अनजान ID के लिए)।"""
    for attempt in (1, 2):
        try:
            return await user.get_chat(ref)
        except (PeerIdInvalid, ChannelInvalid, ValueError):
            if attempt == 1 and not isinstance(ref, str):
                await warm_peer_cache(user)
                continue
            raise ValidationError("Chat नहीं मिला। ID सही है और User account उस chat का member/देख सकने वाला है?")
        except (UsernameInvalid, UsernameNotOccupied):
            raise ValidationError("यह username मौजूद नहीं है।")
    raise ValidationError("Chat नहीं मिला।")  # pragma: no cover


async def check_destination(user, ref) -> ChatInfo:
    chat = await resolve_chat(user, ref)
    _ensure_group_or_channel(chat)
    try:
        me = await user.get_chat_member(chat.id, "me")
    except UserNotParticipant:
        raise ValidationError("User account इस destination का member नहीं है। पहले उसे join/add करें।")
    except (ChannelPrivate, ChatInvalid, ChannelInvalid, ChatRestricted) as e:
        raise ValidationError(describe_error(e))
    err = destination_permission_error(
        chat.type, me.status, me.privileges, me.permissions, chat.permissions
    )
    if err:
        raise ValidationError(err)
    return ChatInfo(chat_id=chat.id, title=chat.title or str(chat.id), kind=chat.type.name)


async def check_source(user, ref) -> ChatInfo:
    chat = await resolve_chat(user, ref)
    _ensure_group_or_channel(chat)
    note = ""
    try:
        me = await user.get_chat_member(chat.id, "me")
        if me.status in (enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED):
            raise ValidationError("User account इस source का member नहीं है या ban है।")
        note = "सदस्य"
    except UserNotParticipant:
        note = "सदस्य नहीं (history देखी जा सकती है तो आगे बढ़ेंगे)"
    except ValidationError:
        raise
    except (ChannelPrivate, ChatInvalid, ChannelInvalid, ChatRestricted):
        raise ValidationError("Source की access नहीं है (private या बिना membership)।")

    try:
        latest = await latest_message_id(user, chat.id)
    except (ChannelPrivate, UserNotParticipant, ChatInvalid, ChannelInvalid, PeerIdInvalid, ChatRestricted):
        raise ValidationError("Source का message history पढ़ने की access नहीं है।")
    if latest == 0:
        raise ValidationError("Source में पढ़ने योग्य कोई message नहीं मिला (या history accessible नहीं)।")
    return ChatInfo(chat_id=chat.id, title=chat.title or str(chat.id), kind=chat.type.name, note=note)


# ─────────────────────────────────────────────
# 📦 JOB STATE
# ─────────────────────────────────────────────
@dataclass
class ForwardJob:
    admin_id: int
    src_id: int
    dst_id: int
    src_title: str = ""
    dst_title: str = ""
    job_id: str | None = None
    status: str = "pending"
    scanned: int = 0
    copied: int = 0
    failed: int = 0
    duplicates: int = 0
    last_scanned_id: int = 0      # checkpoint: इस ID तक सब प्रोसेस हो चुका है
    max_id: int = 0               # शुरू होने के समय source का सबसे नया message ID
    wait_until: float = 0.0       # FloodWait खत्म होने का epoch time
    wait_seconds: int = 0
    error: str = ""
    progress_msg_id: int | None = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


def job_to_fields(job: ForwardJob) -> dict:
    return {
        "admin_id": int(job.admin_id),
        "src_id": int(job.src_id),
        "dst_id": int(job.dst_id),
        "src_title": job.src_title,
        "dst_title": job.dst_title,
        "status": job.status,
        "scanned": job.scanned,
        "copied": job.copied,
        "failed": job.failed,
        "duplicates": job.duplicates,
        "last_scanned_id": job.last_scanned_id,
        "max_id": job.max_id,
        "wait_until": job.wait_until,
        "error": job.error,
    }


def job_from_doc(doc: dict) -> ForwardJob:
    job = ForwardJob(
        admin_id=doc["admin_id"],
        src_id=doc["src_id"],
        dst_id=doc["dst_id"],
        src_title=doc.get("src_title", ""),
        dst_title=doc.get("dst_title", ""),
        job_id=str(doc["_id"]),
    )
    job.status = doc.get("status", "pending")
    job.scanned = doc.get("scanned", 0)
    job.copied = doc.get("copied", 0)
    job.failed = doc.get("failed", 0)
    job.duplicates = doc.get("duplicates", 0)
    job.last_scanned_id = doc.get("last_scanned_id", 0)
    job.max_id = doc.get("max_id", 0)
    job.wait_until = doc.get("wait_until", 0.0) or 0.0
    job.error = doc.get("error", "")
    return job


def resume_block_reason(job: ForwardJob, now: float):
    """Resume न हो सकने का कारण (Hindi) या None।"""
    if job.status not in RESUMABLE_STATUSES:
        return "इस job की स्थिति resume योग्य नहीं है।"
    if job.wait_until and job.wait_until > now:
        remaining = int(job.wait_until - now) + 1
        return f"Telegram FloodWait अभी बाकी है — लगभग {remaining} सेकंड बाद Resume करें।"
    return None


def _fmt_time(epoch: float) -> str:
    try:
        tz = pytz.timezone(TIME_ZONE)
    except Exception:
        tz = pytz.utc
    return datetime.fromtimestamp(epoch, tz).strftime("%d %b %Y, %I:%M:%S %p")


def render_progress(job: ForwardJob) -> str:
    lines = [
        "🎬 <b>Video Copy Job</b>",
        "",
        f"📤 <b>Source:</b> {html.escape(job.src_title or str(job.src_id))} <code>{job.src_id}</code>",
        f"📥 <b>Destination:</b> {html.escape(job.dst_title or str(job.dst_id))} <code>{job.dst_id}</code>",
        "",
        f"🔎 Scanned messages: <code>{job.scanned}</code>",
        f"✅ Videos copied: <code>{job.copied}</code>",
        f"❌ Failed copies: <code>{job.failed}</code>",
        f"♻️ Duplicates skipped: <code>{job.duplicates}</code>",
        f"📍 Checkpoint: <code>{job.last_scanned_id}</code> / <code>{job.max_id}</code>",
        "",
        f"📊 <b>Status:</b> {STATUS_TEXT.get(job.status, html.escape(job.status))}",
    ]
    if job.status == "floodwait" and job.wait_until:
        remaining = max(0, int(job.wait_until - time.time()))
        lines.append(
            f"⏳ Telegram ने <b>{job.wait_seconds or remaining}</b> सेकंड प्रतीक्षा माँगी है "
            f"(लगभग {remaining} सेकंड बाकी, {_fmt_time(job.wait_until)} के बाद)।"
        )
    if job.error:
        lines.append(f"⚠️ <b>कारण:</b> {html.escape(job.error)}")
    return "\n".join(lines)


def stop_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⏹ STOP JOB", callback_data="fwd#stop")]])


# ─────────────────────────────────────────────
# 🔁 TELEGRAM CALL HELPERS
# ─────────────────────────────────────────────
async def _with_network_retry(fn, *args, backoff=NETWORK_BACKOFF):
    """केवल network errors पर सीमित retries; FloodWait/अन्य errors जैसे हैं वैसे ऊपर जाते हैं।"""
    attempt = 0
    while True:
        try:
            return await fn(*args)
        except NETWORK_ERRORS:
            if attempt >= len(backoff):
                raise
            await asyncio.sleep(backoff[attempt])
            attempt += 1


async def _get_messages(user, chat_id, ids):
    res = await user.get_messages(chat_id, ids)
    return res if isinstance(res, list) else [res]


async def _pause(job: ForwardJob, seconds: float):
    """विराम — stop request आने पर तुरंत लौट आता है।"""
    if seconds <= 0:
        return
    try:
        await asyncio.wait_for(job.stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def _persist(store, job: ForwardJob):
    if store is not None and job.job_id:
        await store.update_job(job.job_id, job_to_fields(job))


# ─────────────────────────────────────────────
# 🚜 MAIN RUNNER (store/user/notify inject होते हैं → unit tests में mock किए जा सकते हैं)
# ─────────────────────────────────────────────
async def run_forward_job(
    job: ForwardJob,
    user,
    store,
    notify=None,
    *,
    delay_fn=random_copy_delay,
    retry_backoff=NETWORK_BACKOFF,
    progress_interval=PROGRESS_INTERVAL,
):
    job.status = "running"
    job.error = ""
    job.wait_until = 0.0
    await _persist(store, job)

    last_ui = 0.0

    async def _ui(force=False):
        nonlocal last_ui
        if notify is None:
            return
        now = time.monotonic()
        if force or now - last_ui >= progress_interval:
            last_ui = now
            try:
                await notify(job)
            except Exception as e:  # progress edit की विफलता job रोकती नहीं
                logger.debug(f"progress update skipped: {type(e).__name__}")

    consecutive_failures = 0
    try:
        job.max_id = await _with_network_retry(latest_message_id, user, job.src_id, backoff=retry_backoff)
        cur = job.last_scanned_id + 1
        await _ui(force=True)

        while cur <= job.max_id:
            if job.stop_event.is_set():
                break
            hi = min(cur + SCAN_BATCH - 1, job.max_id)
            batch = await _with_network_retry(
                _get_messages, user, job.src_id, list(range(cur, hi + 1)), backoff=retry_backoff
            )
            halted = False
            for msg in batch:
                if job.stop_event.is_set():
                    halted = True
                    break
                if msg is None or getattr(msg, "empty", False):
                    continue
                job.scanned += 1

                if not is_forwardable_video(msg):
                    job.last_scanned_id = msg.id
                    continue

                if await store.is_copied(job.src_id, job.dst_id, msg.id):
                    job.duplicates += 1
                    job.last_scanned_id = msg.id
                    continue

                try:
                    sent = await _with_network_retry(
                        user.copy_message, job.dst_id, job.src_id, msg.id, backoff=retry_backoff
                    )
                except (FloodWait, SlowmodeWait) as e:
                    # Telegram की सीमा का सम्मान: job रोको, इसी message को Resume पर दोबारा लेंगे
                    job.status = "floodwait"
                    job.wait_seconds = int(e.value)
                    job.wait_until = time.time() + int(e.value)
                    job.error = f"Telegram rate limit — {int(e.value)} सेकंड प्रतीक्षा आवश्यक।"
                    halted = True
                    break
                except Exception as exc:
                    kind = classify_error(exc)
                    if kind in ("stop", "network"):
                        job.status = "error"
                        job.error = describe_error(exc)
                        halted = True
                        break
                    # per-message failure
                    job.failed += 1
                    job.last_scanned_id = msg.id
                    consecutive_failures += 1
                    logger.warning(f"forward: message {msg.id} skipped ({type(exc).__name__})")
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        job.status = "error"
                        job.error = f"लगातार {MAX_CONSECUTIVE_FAILURES} messages fail हुए — job रोका गया।"
                        halted = True
                        break
                    await _ui()
                    continue

                consecutive_failures = 0
                job.copied += 1
                job.last_scanned_id = msg.id
                # सफल copy का रिकॉर्ड पहले, फिर checkpoint — ताकि resume पर दोबारा न भेजा जाए
                await store.mark_copied(job.src_id, job.dst_id, msg.id, getattr(sent, "id", None), job.job_id)
                await _persist(store, job)
                await _ui()
                await _pause(job, delay_fn())

            if halted:
                break
            job.last_scanned_id = hi
            await _persist(store, job)
            await _ui()
            cur = hi + 1

        if job.status == "running":
            job.status = "completed" if job.last_scanned_id >= job.max_id else "stopped"

    except asyncio.CancelledError:
        job.status = "interrupted"
        job.error = "Bot बंद/restart हुआ — progress सुरक्षित है।"
        try:
            await _persist(store, job)
        except Exception:
            pass
        raise
    except (FloodWait, SlowmodeWait) as e:
        job.status = "floodwait"
        job.wait_seconds = int(e.value)
        job.wait_until = time.time() + int(e.value)
        job.error = f"Telegram rate limit — {int(e.value)} सेकंड प्रतीक्षा आवश्यक।"
    except Exception as exc:
        job.status = "error"
        job.error = describe_error(exc)
        logger.error(f"forward job {job.job_id} stopped: {type(exc).__name__}")

    try:
        await _persist(store, job)
    except Exception as e:
        logger.error(f"forward job state save failed: {type(e).__name__}")
    await _ui(force=True)
    return job


# ─────────────────────────────────────────────
# 🧭 JOB REGISTRY (एक समय में केवल एक सक्रिय job)
# ─────────────────────────────────────────────
_active = {"job": None, "task": None}
_store_singleton = None


def get_forward_store():
    global _store_singleton
    if _store_singleton is None:
        from database.forward_db import ForwardStore
        _store_singleton = ForwardStore(main_db.db)
    return _store_singleton


def get_active_job():
    task = _active["task"]
    if task is None or task.done():
        return None
    return _active["job"]


def is_job_running() -> bool:
    return get_active_job() is not None


def make_notifier(bot, job: ForwardJob):
    async def _notify(j: ForwardJob):
        if not j.progress_msg_id:
            return
        markup = stop_markup() if j.status == "running" else None
        try:
            await bot.edit_message_text(j.admin_id, j.progress_msg_id, render_progress(j), reply_markup=markup)
        except Exception as e:
            if "MESSAGE_NOT_MODIFIED" not in str(e):
                logger.debug(f"progress edit skipped: {type(e).__name__}")
    return _notify


async def launch_job(bot, job: ForwardJob, user, store=None, *, retry_backoff=NETWORK_BACKOFF) -> ForwardJob:
    """Job शुरू करता है। Bot से progress message भेजता है, काम User Client से होता है।"""
    if is_job_running():
        raise ForwardError("⚠️ एक job पहले से चल रहा है। पहले /stopforward भेजें।")
    store = store or get_forward_store()
    if job.job_id is None:
        job.job_id = await store.create_job(job_to_fields(job))
    notify = make_notifier(bot, job)
    progress = await bot.send_message(job.admin_id, render_progress(job), reply_markup=stop_markup())
    job.progress_msg_id = progress.id
    _active["job"] = job
    _active["task"] = asyncio.create_task(_job_task(job, user, store, notify, retry_backoff))
    return job


async def _job_task(job, user, store, notify, retry_backoff):
    try:
        await run_forward_job(job, user, store, notify, retry_backoff=retry_backoff)
    except Exception as e:
        logger.error(f"forward task crashed: {type(e).__name__}")
    finally:
        logger.info(f"forward job {job.job_id} finished with status={job.status}")


def request_stop():
    """सक्रिय job को सुरक्षित रोकने का अनुरोध। कोई job न हो तो None।"""
    job = get_active_job()
    if job is None:
        return None
    job.stop_event.set()
    return job


async def shutdown_forward_jobs(timeout: float = 20.0):
    """Bot shutdown पर: job को रोकने का संकेत, फिर timeout के बाद cancel (status 'interrupted' सेव होता है)।"""
    job, task = _active["job"], _active["task"]
    if task is None or task.done():
        return
    job.stop_event.set()
    await asyncio.wait({task}, timeout=timeout)
    if not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    logger.info("✅ Forward job shutdown complete")


async def recover_interrupted_forward_jobs(bot, store=None) -> int:
    """Startup पर: जो jobs 'running' छूटे थे (bot restart/crash), उन्हें 'interrupted' करता है और admin को सूचित करता है।"""
    store = store or get_forward_store()
    await store.ensure_indexes()
    rows = await store.find_jobs_by_status(["running", "pending"])
    for row in rows:
        job_id = str(row["_id"])
        await store.update_job(job_id, {
            "status": "interrupted",
            "error": "Bot restart हुआ — progress सुरक्षित है।",
        })
        try:
            await bot.send_message(
                row["admin_id"],
                "⚠️ <b>Forward job interrupted</b> (bot restart हुआ)।\n"
                f"Source: <code>{row['src_id']}</code> → Destination: <code>{row['dst_id']}</code>\n"
                f"Copied: <code>{row.get('copied', 0)}</code>, checkpoint: <code>{row.get('last_scanned_id', 0)}</code>\n\n"
                "जारी करने के लिए <code>/forward</code> भेजें और ▶️ Resume चुनें। "
                "पहले कॉपी हुए वीडियो दोबारा नहीं भेजे जाएँगे।",
            )
        except Exception as e:
            logger.debug(f"interrupted-job notice skipped: {type(e).__name__}")
    if rows:
        logger.info(f"⚠️ {len(rows)} interrupted forward job(s) marked for resume")
    return len(rows)
