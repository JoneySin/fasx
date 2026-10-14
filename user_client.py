"""
👤 TELEGRAM USER ACCOUNT CLIENT (Bot Client से पूरी तरह अलग)

Session का स्रोत (पहला जो उपलब्ध हो):
  1. `USER_SESSION_STRING` env (Koyeb Secret) — यदि सेट है तो यही प्राथमिक।
  2. Bot के अंदर `/forward` से किया गया login (phone → OTP → 2FA) — परिणामी session
     `ForwardAccount` collection में सेव होता है, ताकि restart पर OTP दोबारा न माँगा जाए।

Login flow (Telegram का official MTProto flow):
  send_code → sign_in (OTP) → [SessionPasswordNeeded पर] check_password (2FA) → export_session_string

सुरक्षा:
- OTP और 2FA password कभी DB, log या किसी बाहरी जगह सेव नहीं होते — केवल memory में, उपयोग के तुरंत बाद।
- Session string कभी log नहीं होता; error messages में भी नहीं।
- User client `in_memory=True` और `no_updates=True` है (कोई .session file नहीं, कोई update handler नहीं)।
"""

import asyncio
import logging
import re

from hydrogram import Client
from hydrogram.errors import (
    AuthKeyInvalid,
    AuthKeyUnregistered,
    FloodWait,
    PasswordHashInvalid,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberInvalid,
    SessionExpired,
    SessionPasswordNeeded,
    SessionRevoked,
    Unauthorized,
    UserDeactivated,
)

from info import API_ID, API_HASH, USER_SESSION_STRING

logger = logging.getLogger(__name__)

CLIENT_NAME = "fasx_user_account"
LOGIN_CLIENT_NAME = "fasx_user_login"

MSG_SESSION_MISSING = (
    "🔐 <b>User account अभी login नहीं है।</b>\n\n"
    "<code>/forward</code> भेजें — bot आपसे Telegram phone number और OTP माँगेगा "
    "(2FA हो तो password भी)। Login के बाद session अपने-आप सेव हो जाएगा।"
)

MSG_SESSION_INVALID_SAVED = (
    "❌ <b>सेव किया गया User session expire या revoke हो चुका है।</b>\n\n"
    "<code>/forward</code> भेजें — नया login शुरू होगा।"
)

MSG_SESSION_INVALID_ENV = (
    "❌ <b>USER_SESSION_STRING (env) invalid, expired या revoked है।</b>\n\n"
    "Recovery: Koyeb में <code>USER_SESSION_STRING</code> Secret हटा दें (तब bot से login होगा), "
    "या नई value डालें और redeploy करें।"
)

LOGIN_PHONE_PROMPT = (
    "🔐 <b>User account login — Step 1/2</b>\n\n"
    "अपना Telegram phone number country code के साथ भेजें, जैसे <code>+919999999999</code>।\n"
    "Telegram उसी account पर OTP भेजेगा।\n\n"
    "रद्द करने के लिए /cancel"
)

_AUTH_ERRORS = (
    AuthKeyInvalid,
    AuthKeyUnregistered,
    SessionExpired,
    SessionRevoked,
    UserDeactivated,
    Unauthorized,
)


class UserSessionError(Exception):
    """User-facing error। Message में कोई secret नहीं।
    needs_login=True हो तो /forward से bot के अंदर login कराया जा सकता है।"""

    def __init__(self, message: str, needs_login: bool = False):
        super().__init__(message)
        self.needs_login = needs_login


_client = None
_start_lock = asyncio.Lock()
_runtime_session = None      # DB से लोड या login के बाद का session string (memory में)
_login = {"client": None, "phone": None, "hash": None}


# ─────────────────────────────────────────────
# SESSION SOURCE
# ─────────────────────────────────────────────
def get_session_string() -> str:
    if USER_SESSION_STRING:
        return USER_SESSION_STRING
    return _runtime_session or ""


def is_session_configured() -> bool:
    return bool(get_session_string())


def session_source():
    if USER_SESSION_STRING:
        return "env"
    if _runtime_session:
        return "saved"
    return None


def get_user_client():
    """चालू (connected) user client लौटाता है, वरना None।"""
    if _client is not None and getattr(_client, "is_connected", False):
        return _client
    return None


async def _store():
    from forward_service import get_forward_store  # lazy: circular import से बचाव
    return get_forward_store()


async def load_saved_session() -> None:
    """env न हो तो DB में सेव session memory में लोड करता है।"""
    global _runtime_session
    if USER_SESSION_STRING:
        return
    try:
        _runtime_session = await (await _store()).load_session() or None
    except Exception as e:
        logger.error(f"Saved user session load failed: {type(e).__name__}")


async def save_session(session_string: str) -> None:
    global _runtime_session
    _runtime_session = session_string
    await (await _store()).save_session(session_string)
    logger.info("✅ User account session saved (DB) — OTP अगली बार नहीं माँगा जाएगा")


async def _clear_saved_session() -> None:
    global _runtime_session
    _runtime_session = None
    try:
        await (await _store()).clear_session()
    except Exception as e:
        logger.error(f"Saved user session clear failed: {type(e).__name__}")


# ─────────────────────────────────────────────
# CLIENT LIFECYCLE
# ─────────────────────────────────────────────
def _build_client() -> Client:
    return Client(
        name=CLIENT_NAME,
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=get_session_string(),  # implies in_memory=True
        in_memory=True,
        no_updates=True,
    )


async def _safe_stop(client) -> None:
    try:
        if getattr(client, "is_connected", False):
            await client.stop()
    except Exception as e:
        logger.debug(f"User client stop ignored: {type(e).__name__}")


async def _safe_disconnect(client) -> None:
    try:
        if getattr(client, "is_connected", False):
            await client.disconnect()
    except Exception as e:
        logger.debug(f"Login client disconnect ignored: {type(e).__name__}")


async def ensure_user_client() -> Client:
    """User client चालू करता है। Session न हो तो needs_login=True वाला UserSessionError।"""
    global _client
    client = get_user_client()
    if client is not None:
        return client

    if not is_session_configured():
        await load_saved_session()
    if not is_session_configured():
        raise UserSessionError(MSG_SESSION_MISSING, needs_login=True)

    async with _start_lock:
        client = get_user_client()
        if client is not None:
            return client

        source = session_source()
        client = _build_client()
        try:
            await client.start()
        except (AuthKeyInvalid, AuthKeyUnregistered, SessionExpired, SessionRevoked,
                UserDeactivated, Unauthorized):
            await _safe_stop(client)
            if source == "saved":
                await _clear_saved_session()
                raise UserSessionError(MSG_SESSION_INVALID_SAVED, needs_login=True) from None
            raise UserSessionError(MSG_SESSION_INVALID_ENV) from None
        except Exception as e:
            await _safe_stop(client)
            raise UserSessionError(
                f"❌ User account से connect नहीं हो सका ({type(e).__name__})। "
                "थोड़ी देर बाद दोबारा प्रयास करें।"
            ) from None

        _client = client
        logger.info(f"✅ User account client connected (session source: {source})")
        return client


async def start_user_client() -> bool:
    """Bot startup पर बुलाया जाता है। कभी exception नहीं फेंकता।"""
    await load_saved_session()
    if not is_session_configured():
        logger.info("ℹ️ User account not logged in — /forward से login करें")
        return False
    try:
        await ensure_user_client()
        return True
    except UserSessionError as e:
        first_line = str(e).splitlines()[0].replace("<b>", "").replace("</b>", "")
        logger.error(f"User account client not started: {first_line}")
        return False


async def stop_user_client() -> None:
    global _client
    client, _client = _client, None
    if client is not None:
        await _safe_stop(client)
        logger.info("✅ User account client stopped")


async def warm_peer_cache(client) -> None:
    """Restart के बाद अनजान chat ID resolve न होने पर एक बार dialogs लोड करता है।"""
    if getattr(client, "_fasx_dialogs_loaded", False):
        return
    async for _ in client.get_dialogs():
        pass
    client._fasx_dialogs_loaded = True


# ─────────────────────────────────────────────
# IN-BOT LOGIN (phone → OTP → optional 2FA)
# ─────────────────────────────────────────────
def is_login_active() -> bool:
    return _login["client"] is not None


def normalize_phone(text: str) -> str:
    phone = re.sub(r"[\s\-()]", "", text or "")
    if not re.fullmatch(r"\+\d{7,15}", phone):
        raise UserSessionError(
            "❌ Phone number country code के साथ सही format में दें, जैसे <code>+919999999999</code>।"
        )
    return phone


async def cancel_login() -> None:
    client = _login["client"]
    _login.update(client=None, phone=None, hash=None)
    if client is not None:
        await _safe_disconnect(client)


async def begin_login(phone_text: str) -> None:
    """Step 1: phone लेकर OTP भेजता है।"""
    phone = normalize_phone(phone_text)
    await cancel_login()
    client = Client(
        name=LOGIN_CLIENT_NAME, api_id=API_ID, api_hash=API_HASH, in_memory=True, no_updates=True
    )
    try:
        await client.connect()
        sent = await client.send_code(phone)
    except PhoneNumberInvalid:
        await _safe_disconnect(client)
        raise UserSessionError("❌ यह phone number Telegram पर valid नहीं है। दोबारा भेजें या /cancel।")
    except FloodWait as e:
        await _safe_disconnect(client)
        raise UserSessionError(f"⏳ Telegram ने {e.value} सेकंड प्रतीक्षा माँगी है। बाद में /forward भेजें।")
    except Exception as e:
        await _safe_disconnect(client)
        logger.error(f"login send_code failed: {type(e).__name__}")
        raise UserSessionError("❌ OTP भेजा नहीं जा सका। बाद में /forward से दोबारा प्रयास करें।")
    _login.update(client=client, phone=phone, hash=sent.phone_code_hash)


async def _complete_login() -> None:
    """Login पूरा: session export → सेव → main user client चालू।"""
    client = _login["client"]
    try:
        session_string = await client.export_session_string()
    finally:
        await cancel_login()
    await save_session(session_string)
    await stop_user_client()
    await ensure_user_client()


async def submit_login_code(code: str) -> bool:
    """Step 2: OTP। True = login पूरा; False = 2FA password चाहिए।"""
    client = _login["client"]
    if client is None:
        raise UserSessionError("❌ Login session नहीं मिला। /forward से फिर शुरू करें।")
    try:
        await client.sign_in(_login["phone"], _login["hash"], code)
    except SessionPasswordNeeded:
        return False
    except PhoneCodeInvalid:
        raise UserSessionError("❌ OTP गलत है। दोबारा भेजें (या /cancel)।")
    except PhoneCodeExpired:
        await cancel_login()
        raise UserSessionError("❌ OTP expire हो गया। /forward से फिर शुरू करें।")
    except FloodWait as e:
        await cancel_login()
        raise UserSessionError(f"⏳ Telegram ने {e.value} सेकंड प्रतीक्षा माँगी है। बाद में /forward भेजें।")
    await _complete_login()
    return True


async def submit_login_password(password: str) -> None:
    """Step 3 (2FA): password। सफल होने पर login पूरा।"""
    client = _login["client"]
    if client is None:
        raise UserSessionError("❌ Login session नहीं मिला। /forward से फिर शुरू करें।")
    try:
        await client.check_password(password)
    except PasswordHashInvalid:
        raise UserSessionError("❌ 2FA password गलत है। दोबारा भेजें (या /cancel)।")
    except FloodWait as e:
        await cancel_login()
        raise UserSessionError(f"⏳ Telegram ने {e.value} सेकंड प्रतीक्षा माँगी है। बाद में /forward भेजें।")
    await _complete_login()
