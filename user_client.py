"""
👤 TELEGRAM USER ACCOUNT CLIENT (Bot Client से पूरी तरह अलग)

- Session केवल `USER_SESSION_STRING` environment secret से लोड होता है।
  कोई `.session` फाइल नहीं बनती (in_memory=True), इसलिए repo/Docker image में session नहीं जाता।
- `no_updates=True`: इस client पर कोई update handler नहीं है, इसलिए account के सभी
  incoming updates process नहीं होते (RAM बचत)।
- OTP और 2FA password यहाँ कभी नहीं माँगे जाते — वे केवल `generate_session.py`
  में Telegram के official login flow (send_code → sign_in → check_password) से लिए जाते हैं।
- Error messages में session string, OTP या password कभी नहीं आते।
"""

import asyncio
import logging

from hydrogram import Client
from hydrogram.errors import (
    AuthKeyInvalid,
    AuthKeyUnregistered,
    SessionExpired,
    SessionRevoked,
    Unauthorized,
    UserDeactivated,
)

from info import API_ID, API_HASH, USER_SESSION_STRING

logger = logging.getLogger(__name__)

CLIENT_NAME = "fasx_user_account"

MSG_SESSION_MISSING = (
    "❌ <b>USER_SESSION_STRING सेट नहीं है।</b>\n\n"
    "<b>Recovery steps:</b>\n"
    "1. Project folder में चलाएँ: <code>python generate_session.py</code>\n"
    "2. Telegram login पूरा करें (phone → OTP → 2FA password, अगर सेट हो)।\n"
    "3. Script द्वारा दिया गया session string कॉपी करें।\n"
    "4. Koyeb → Service → Environment Variables में <code>USER_SESSION_STRING</code> "
    "को <b>Secret</b> के रूप में जोड़ें।\n"
    "5. Service को redeploy/restart करें।\n\n"
    "⚠️ Session string कहीं भी chat, GitHub या public log में paste न करें।"
)

MSG_SESSION_INVALID = (
    "❌ <b>User session invalid, expired या revoked है</b> (या account deactivate हो गया है)।\n\n"
    "<b>Recovery steps:</b>\n"
    "1. <code>python generate_session.py</code> दोबारा चलाकर नया session string बनाएँ।\n"
    "2. Koyeb में <code>USER_SESSION_STRING</code> Secret को नई value से update करें।\n"
    "3. Service को redeploy/restart करें।\n\n"
    "ℹ️ अगर Telegram → Settings → Devices से session terminate किया गया था, तो नया login ज़रूरी है।"
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
    """User-facing error। इसके message में कोई secret नहीं होता।"""


_client = None
_start_lock = asyncio.Lock()


def is_session_configured() -> bool:
    return bool(USER_SESSION_STRING)


def get_user_client():
    """चालू (connected) user client लौटाता है, वरना None।"""
    if _client is not None and getattr(_client, "is_connected", False):
        return _client
    return None


def _build_client() -> Client:
    return Client(
        name=CLIENT_NAME,
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=USER_SESSION_STRING,  # implies in_memory=True
        in_memory=True,
        no_updates=True,
    )


async def _safe_stop(client) -> None:
    try:
        if getattr(client, "is_connected", False):
            await client.stop()
    except Exception as e:  # stop के error से bot shutdown न रुके
        logger.debug(f"User client stop ignored: {type(e).__name__}")


async def ensure_user_client() -> Client:
    """User client चालू करता है (पहली बार या दोबारा)। असफल होने पर UserSessionError।"""
    global _client
    client = get_user_client()
    if client is not None:
        return client

    if not is_session_configured():
        raise UserSessionError(MSG_SESSION_MISSING)

    async with _start_lock:
        client = get_user_client()
        if client is not None:
            return client

        client = _build_client()
        try:
            await client.start()
        except _AUTH_ERRORS:
            await _safe_stop(client)
            raise UserSessionError(MSG_SESSION_INVALID) from None
        except Exception as e:
            await _safe_stop(client)
            # केवल exception का प्रकार दिखाते हैं — message में session जानकारी हो सकती है
            raise UserSessionError(
                f"❌ User account से connect नहीं हो सका ({type(e).__name__})। "
                "थोड़ी देर बाद दोबारा प्रयास करें।"
            ) from None

        _client = client
        logger.info("✅ User account client connected (session loaded from environment)")
        return client


async def start_user_client() -> bool:
    """Bot startup पर बुलाया जाता है। कभी exception नहीं फेंकता — bot सामान्य चलता रहता है।"""
    if not is_session_configured():
        logger.info("ℹ️ USER_SESSION_STRING not set — /forward feature disabled until configured")
        return False
    try:
        await ensure_user_client()
        return True
    except UserSessionError as e:
        # HTML tags हटाकर संक्षिप्त संदेश; session string यहाँ कभी नहीं होता
        first_line = str(e).splitlines()[0].replace("<b>", "").replace("</b>", "")
        logger.error(f"User account client not started: {first_line}")
        return False


async def stop_user_client() -> None:
    """Bot shutdown पर बुलाया जाता है।"""
    global _client
    client, _client = _client, None
    if client is not None:
        await _safe_stop(client)
        logger.info("✅ User account client stopped")


async def warm_peer_cache(client) -> None:
    """Session in-memory होने से restart के बाद peers (chat access hashes) खाली होते हैं।
    अनजान chat ID resolve न होने पर एक बार dialogs लोड करके cache भर दिया जाता है।"""
    if getattr(client, "_fasx_dialogs_loaded", False):
        return
    async for _ in client.get_dialogs():
        pass
    client._fasx_dialogs_loaded = True
