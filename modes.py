"""
🧠 MULTI-BOT MODE ENGINE (Single Source Of Truth)
==================================================

Is repo ko ek hi code-base se do alag "bots" chalte hain:

1. 🎬 ``MODE_FILTER``    — **Auto Filter Bot**   (search / mini app / streaming)
2. 🛡️ ``MODE_MGMT``     — **Group Manager Bot** (blacklist / warn / ban / report)

Do bilkul alag axes hain — dono ek doosre se independent hain:

┌──────────────┬──────────────────────────────────────────────────────────┐
│  USER MODE   │ Ek USER ka PM menu kaisa dikhega.                        │
│              │  • ``None``            → user ne abhi choose nahi kiya   │
│              │  • ``MODE_FILTER``     → Auto Filter wala experience      │
│              │  • ``MODE_MGMT``       → Group Manager wala experience    │
├──────────────┼──────────────────────────────────────────────────────────┤
│  GROUP MODE  │ Ek GROUP me bot kya karega.                              │
│              │  • ``MODE_MGMT``       → sirf group-management features  │
│              │  • ``MODE_FILTER``     → sirf auto-filter features        │
└──────────────┴──────────────────────────────────────────────────────────┘

📌 USER ka final rule (yahi implement kiya gaya hai):
• Bot jab bhi kisi group me ADD hota hai → group mode = **MANAGEMENT**
  (yaani us group me auto-filter CHALEGA HI NAHI).
• Bot ADMIN jab bot ke PM me group ka ID register karta hai
  (``/add_group <id>``) → us group ka mode = **FILTER**
  (yaani us group me auto-filter CHALEGA).

Free user ko default me GROUP-MANAGER experience milta hai (public users ke
liye "group management bot" lagna hi tha), aur niche premium-join button
dikhta hai. Admin / Premium users ko pehli ``/start`` par choice screen
milta hai — jo bhi button dabayenge, wahi unka permanent mode ban jata hai.
"""

import logging
import time

from info import ADMINS
from database.users_chats_db import db

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 🎯 MODE CONSTANTS
# ─────────────────────────────────────────────
MODE_FILTER = "filter"
MODE_MGMT = "management"
VALID_MODES = (MODE_FILTER, MODE_MGMT)

# Group me bot add hone par default (bot admin ke PM registration ke alawa)
DEFAULT_GROUP_MODE = MODE_MGMT

# Free / public user ka default experience
DEFAULT_FREE_USER_MODE = MODE_MGMT

# ─────────────────────────────────────────────
# ⚡ TINY TTL CACHE (per-message DB hit nahi)
# ─────────────────────────────────────────────
_CACHE_TTL = 60       # 60 second — mode switch turant reflect kare
_MAX_CACHE = 500      # bounded (Koyeb RAM safe)
_cache = {}

_NOSTORE = "__none__"


def _cache_get(key):
    item = _cache.get(key)
    if item is None:
        return None
    value, ts = item
    if time.time() - ts > _CACHE_TTL:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key, value):
    if len(_cache) > _MAX_CACHE:
        _cache.clear()
    _cache[key] = (value, time.time())


def invalidate_cache(key=None):
    """Mode cache manually clear (tests / admin force-switch ke liye)."""
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


# ─────────────────────────────────────────────
# 🧩 MODE NORMALISER
# ─────────────────────────────────────────────
_MODE_ALIASES = {
    "filter": MODE_FILTER,
    "autofilter": MODE_FILTER,
    "auto_filter": MODE_FILTER,
    "auto-filter": MODE_FILTER,
    "auto": MODE_FILTER,
    "search": MODE_FILTER,
    "movie": MODE_FILTER,

    "management": MODE_MGMT,
    "mgmt": MODE_MGMT,
    "group": MODE_MGMT,
    "groupmanager": MODE_MGMT,
    "group_manager": MODE_MGMT,
    "group-management": MODE_MGMT,
    "moderation": MODE_MGMT,
    "protect": MODE_MGMT,
}


def normalize_mode(value):
    """Kisi bhi string/None ko canonical mode me convert karta hai.

    Return ``None`` agar value valid mode na ho (matlab "abhi set nahi hua").
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if not v:
        return None
    return _MODE_ALIASES.get(v)


# ─────────────────────────────────────────────
# 👤 USER MODE
# ─────────────────────────────────────────────
async def get_user_mode(uid):
    """User ka saved mode — ``None`` matlab abhi choose nahi kiya."""
    uid = int(uid)
    key = ("u", uid)
    cached = _cache_get(key)
    if cached is not None:
        return None if cached == _NOSTORE else cached

    try:
        raw = await db.get_user_mode(uid)
    except Exception as e:
        logger.error(f"get_user_mode({uid}) failed: {e}")
        raw = None

    mode = normalize_mode(raw)
    _cache_set(key, mode or _NOSTORE)
    return mode


async def set_user_mode(uid, mode):
    """User ka mode save karta hai (permanent choice)."""
    uid = int(uid)
    mode = normalize_mode(mode)
    if not mode:
        return False
    try:
        await db.set_user_mode(uid, mode)
    except Exception as e:
        logger.error(f"set_user_mode({uid}) failed: {e}")
        return False
    _cache_set(("u", uid), mode)
    return True


async def effective_user_mode(uid, premium=False):
    """PM menu ke liye effective mode.

    • user ne mode choose kar liya      → wahi
    • admin / premium (choose nahi kiya) → ``None`` (choice screen dikhega)
    • free user (choose nahi kiya)      → ``MODE_MGMT`` (default experience)
    """
    mode = await get_user_mode(uid)
    if mode:
        return mode
    if int(uid) in ADMINS or premium:
        return None
    return DEFAULT_FREE_USER_MODE


async def is_premium_capable(uid):
    """True agar user premium ya bot-admin hai (mode choice ka adhikar)."""
    if int(uid) in ADMINS:
        return True
    try:
        from utils import is_premium
        return await is_premium(int(uid))
    except Exception as e:
        logger.debug(f"is_premium_capable({uid}) failed: {e}")
        return False


# ─────────────────────────────────────────────
# 👥 GROUP MODE
# ─────────────────────────────────────────────
async def get_group_mode(gid):
    """Group ka effective mode.

    3 cases:
    1. mode DB me saved hai            → wahi (FILTER / MANAGEMENT)
    2. group DB me hai par mode nahi   → **FILTER** (legacy auto-filter
       deployment — pehle se chal rahe groups ka behaviour nahi tootna chahiye)
    3. group DB me hi nahi hai         → **MANAGEMENT** (naya add: bot group me
       जोड़ा gaya hai to group-manager banta hai, auto-filter nahi)
    """
    gid = int(gid)
    key = ("g", gid)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        registered, raw = await db.get_group_mode_info(gid)
    except Exception as e:
        logger.error(f"get_group_mode({gid}) failed: {e}")
        registered, raw = False, None

    mode = normalize_mode(raw)
    if not mode:
        mode = MODE_FILTER if registered else DEFAULT_GROUP_MODE

    _cache_set(key, mode)
    return mode


async def set_group_mode(gid, mode):
    """Group ka mode save karta hai (admin registration / switch)."""
    gid = int(gid)
    mode = normalize_mode(mode)
    if not mode:
        return False
    try:
        await db.set_group_mode(gid, mode)
    except Exception as e:
        logger.error(f"set_group_mode({gid}) failed: {e}")
        return False
    _cache_set(("g", gid), mode)
    return True


async def ensure_mode_after_bot_add(gid):
    """Bot jab group me ADD hota hai tab ka rule.

    Default: mode = **MANAGEMENT** (group me manually add hone par auto-filter
    nahi chalega — user ka rule).

    ⚠️ Exception: agar group pehle se bot-admin ke PM se Auto Filter ke liye
    **register** hai (``/add_group``), to admin ka decision override nahi hota —
    warna admin ka register kiya hua group, dobara add karne par chup-chaap
    group-manager ban jata.
    """
    try:
        registered, raw = await db.get_group_mode_info(gid)
    except Exception as e:
        logger.error(f"ensure_mode_after_bot_add({gid}) read failed: {e}")
        registered, raw = False, None

    if registered and normalize_mode(raw) == MODE_FILTER:
        return MODE_FILTER

    await set_group_mode(gid, MODE_MGMT)
    return MODE_MGMT


async def is_filter_group(gid):
    """True → is group me AUTO-FILTER chalta hai."""
    return (await get_group_mode(gid)) == MODE_FILTER


async def is_mgmt_group(gid):
    """True → is group me sirf GROUP-MANAGEMENT chalta hai."""
    return (await get_group_mode(gid)) == MODE_MGMT


async def list_group_modes():
    """Sabhi registered groups + unka mode (admin listing ke liye)."""
    out = []
    try:
        async for doc in db.groups.find({}, {"id": 1, "title": 1, "mode": 1}):
            out.append({
                "id": doc.get("id"),
                "title": doc.get("title") or "Unknown",
                "mode": normalize_mode(doc.get("mode")) or DEFAULT_GROUP_MODE,
            })
    except Exception as e:
        logger.error(f"list_group_modes failed: {e}")
    return out
