"""
🔐 USER SESSION SETUP — एक बार चलाएँ (Bot चलाने से पहले, अपने computer पर)

    python generate_session.py

- Telegram के official login flow का उपयोग: send_code → sign_in → (2FA हो तो) check_password
- OTP और 2FA password केवल terminal में पूछे जाते हैं; इन्हें कहीं सेव, print या log नहीं किया जाता।
- अंत में एक `session string` दिखता है — इसे Koyeb में `USER_SESSION_STRING` Secret के रूप में रखें।
  इसे GitHub, chat, screenshot या logs में न डालें। यह आपके Telegram account का पूरा access है।
- कोई .session फाइल नहीं बनती (in_memory).

API_ID / API_HASH env से लिए जाते हैं (या पूछे जाते हैं)। इस script को info.py की ज़रूरत नहीं।
"""

import asyncio
import getpass
import os
import sys

from hydrogram import Client
from hydrogram.errors import (
    FloodWait,
    PasswordHashInvalid,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    SessionPasswordNeeded,
)


def _read_api_credentials():
    api_id = (os.environ.get("API_ID") or "").strip() or input("API_ID (my.telegram.org): ").strip()
    api_hash = (os.environ.get("API_HASH") or "").strip() or getpass.getpass("API_HASH (छिपाकर लिखा जाएगा): ").strip()
    if not api_id.isdigit() or not api_hash:
        sys.exit("❌ API_ID (संख्या) और API_HASH सही दें।")
    return int(api_id), api_hash


async def main():
    print("=" * 60)
    print(" Telegram USER session setup")
    print(" ⚠️ यह session आपके account का पूरा access देता है। सुरक्षित रखें।")
    print("=" * 60)

    api_id, api_hash = _read_api_credentials()
    phone = input("Phone number (country code सहित, जैसे +919999999999): ").strip()
    if not phone.startswith("+"):
        sys.exit("❌ Phone number '+' और country code के साथ दें।")

    client = Client(
        name="generate_user_session",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True,
        no_updates=True,
    )
    await client.connect()
    session_string = None
    try:
        sent = await client.send_code(phone)
        print("📨 Telegram ने OTP भेजा है (app/SMS में देखें)।")
        code = input("OTP: ").strip().replace(" ", "").replace("-", "")
        try:
            await client.sign_in(phone, sent.phone_code_hash, code)
        except SessionPasswordNeeded:
            print("🔑 इस account पर 2FA सक्रिय है।")
            password = getpass.getpass("2FA password (टाइप दिखाई नहीं देगा): ")
            await client.check_password(password)
            password = None

        session_string = await client.export_session_string()
    except PhoneCodeInvalid:
        sys.exit("❌ OTP गलत है। script दोबारा चलाएँ।")
    except PhoneCodeExpired:
        sys.exit("❌ OTP expire हो गया है। script दोबारा चलाएँ।")
    except PasswordHashInvalid:
        sys.exit("❌ 2FA password गलत है। script दोबारा चलाएँ।")
    except FloodWait as e:
        sys.exit(f"❌ Telegram ने {e.value} सेकंड प्रतीक्षा माँगी है। बाद में प्रयास करें।")
    finally:
        await client.disconnect()

    print()
    print("✅ Login सफल। नीचे दिया session string Koyeb में USER_SESSION_STRING (Secret) के रूप में सेट करें:")
    print("-" * 60)
    print(session_string)
    print("-" * 60)
    print("⚠️ इसे कॉपी करने के बाद terminal history/screen साफ़ करें। कहीं और paste न करें।")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nरद्द किया गया।")
