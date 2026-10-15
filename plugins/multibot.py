"""
🧠 MULTI-BOT CONTROL PLUGIN (User Mode + Group Registry)
=========================================================

Ye plugin "ek bot, do personalities" ka brain hai:

👤 <b>USER MODE</b> (PM behaviour)
• Admin / Premium users ko pehli ``/start`` par choice screen milta hai
  (🎬 Auto Filter  vs  🛡️ Group Manager) — jo chune, wahi unka permanent mode.
• Free / public users ko default me <b>Group Manager</b> experience milta hai
  (features + buttons + neeche 💎 premium-join button).

👥 <b>GROUP MODE</b> (group behaviour) — bot-admin ke PM se control hota hai
• ``/add_group <chat_id>``  → group register + mode = <b>FILTER</b> (auto-filter)
• ``/rm_group <chat_id>``  → unregister + mode = <b>MANAGEMENT</b>
• ``/set_gmode <chat_id> <mode>`` → explicit switch
• ``/list_groups``          → sabhi groups + unka live mode

Default rule (user ka instruction): bot jab group me add hota hai → mode
MANAGEMENT (auto-filter wahan CHALEGA HI NAHI). Admin ke PM registration se
group FILTER mode me chala jata hai.
"""

import logging

from hydrogram import Client, filters
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from database.users_chats_db import db
from groupmgmt.menu import build_gm_menu
from info import ADMINS, LOG_CHANNEL, URL
from modes import (
    MODE_FILTER, MODE_MGMT, effective_user_mode, get_user_mode, is_premium_capable,
    list_group_modes, normalize_mode, set_group_mode, set_user_mode,
)
from groupmgmt.core import esc
from Script import script
from utils import build_mini_app_url, get_wish, temp

MINI_APP_URL = build_mini_app_url(URL)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 🎛 MODE PICKER
# ─────────────────────────────────────────────
def mode_picker_markup():
    """Choice screen ke do bade buttons."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Auto Filter Bot", callback_data=f"mode_pick#{MODE_FILTER}")],
        [InlineKeyboardButton("🛡️ Group Manager Bot", callback_data=f"mode_pick#{MODE_MGMT}")],
    ])


async def resolve_start_state(user):
    """``/start`` ke liye user ka state decide karta hai.

    ⚠️ ``user`` = asli Telegram User object (``message.from_user`` ya
    ``query.from_user``). Callback ke case me ``query.message.from_user``
    BOT hota hai — isliye ye function message nahi, user leta hai.

    Returns ``"pick"`` (mode choose karna hai) ya ek mode string
    (``MODE_FILTER`` / ``MODE_MGMT``).
    """
    uid = user.id
    stored = await get_user_mode(uid)
    if stored:
        return stored

    # Admin / Premium → choice screen
    if await is_premium_capable(uid):
        return "pick"

    # Free / public user → default Group Manager experience
    return MODE_MGMT


async def build_mode_menu(user, mode):
    """Mode ke hisaab se PM menu ka (caption, markup) banata hai.

    ``user`` = Telegram User (dekho ``resolve_start_state`` ka note).
    """
    uid = user.id
    premium = await is_premium_capable(uid)

    if mode == MODE_MGMT:
        text, markup = build_gm_menu(uid, premium=premium, is_admin_user=uid in ADMINS)
        return text, markup

    # ── Auto Filter menu (classic) ──
    btn = [
        [InlineKeyboardButton("🍿 Open Mini App", web_app=WebAppInfo(url=MINI_APP_URL))],
        [InlineKeyboardButton("+ Add to Group +", url=f"https://t.me/{temp.U_NAME}?startgroup=start")],
        [InlineKeyboardButton("👨‍🚒 Help Menu", callback_data="help"),
         InlineKeyboardButton("📊 Global Stats", callback_data="stats")],
    ]
    if uid not in ADMINS:
        btn.append([InlineKeyboardButton("💎 Premium Duration", callback_data="myplan")])
    btn.append([InlineKeyboardButton("🔄 Switch Bot Mode", callback_data="mode_open")])

    return script.START_TXT.format(user.mention, get_wish()), InlineKeyboardMarkup(btn)


# ─────────────────────────────────────────────
# 🎬 MODE SELECTION CALLBACKS
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^mode_pick#"))
async def mode_pick_cb(client, query):
    """User apna permanent mode choose karta hai."""
    try:
        mode = normalize_mode(query.data.split("#", 1)[1])
        if not mode:
            return await query.answer("❌ Invalid mode.", show_alert=True)

        uid = query.from_user.id
        if not await is_premium_capable(uid):
            # Free users ko filter-mode nahi milta — unhe premium CTA dikhao
            await query.answer(
                "💎 Premium required to switch mode. Group Manager mode aapke liye free hai!",
                show_alert=True)
            gm_text = script.GM_START_TXT.format(query.from_user.mention, get_wish())
            gm_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Join Premium", callback_data="activate_plan")],
            ])
            try:
                # /start ka message photo+caption hota hai, isliye pehle caption
                await query.message.edit_caption(caption=gm_text, reply_markup=gm_markup)
            except Exception:
                try:
                    await query.message.edit_text(text=gm_text, reply_markup=gm_markup)
                except Exception:
                    pass
            return

        await set_user_mode(uid, mode)
        await query.answer("✅ Mode set!", show_alert=False)

        text, markup = await build_mode_menu(query.from_user, mode)
        try:
            await query.message.edit_caption(caption=text, reply_markup=markup)
        except Exception:
            try:
                await query.message.edit_text(text=text, reply_markup=markup)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"mode_pick_cb error: {e}")


@Client.on_callback_query(filters.regex(r"^mode_open$"))
async def mode_open_cb(client, query):
    """Mode-switch screen kholta hai (switch karne ke liye)."""
    try:
        uid = query.from_user.id
        if not await is_premium_capable(uid):
            return await query.answer(
                "💎 Premium required to switch mode. Group Manager mode aapke liye free hai!",
                show_alert=True)

        text = script.MODE_PICK_TXT.format(query.from_user.mention, get_wish())
        try:
            await query.message.edit_caption(caption=text, reply_markup=mode_picker_markup())
        except Exception:
            await query.message.edit_text(text=text, reply_markup=mode_picker_markup())
    except Exception as e:
        logger.error(f"mode_open_cb error: {e}")


@Client.on_message(filters.command(["mode"]) & filters.private)
async def mode_cmd(client, message):
    """Current mode dikhata hai + switch button."""
    uid = message.from_user.id
    premium = await is_premium_capable(uid)

    # effective_user_mode: saved choice > (premium/admin = None → picker) >
    # free user = Group Manager (default experience).
    mode = await effective_user_mode(uid, premium=premium)

    if mode is None:
        return await message.reply(
            script.MODE_PICK_TXT.format(message.from_user.mention, get_wish()),
            reply_markup=mode_picker_markup())

    stored = await get_user_mode(uid)
    if mode == MODE_FILTER:
        label = "🎬 Auto Filter Bot"
    else:
        label = ("🛡️ Group Manager Bot" if stored
                 else "🛡️ Group Manager Bot (default for free users)")
    text = script.MODE_INFO_TXT.format(label)

    rows = []
    if premium:
        rows.append([InlineKeyboardButton("🔄 Switch Bot Mode", callback_data="mode_open")])
    rows.append([InlineKeyboardButton("⬅️ Back Menu", callback_data="back_start")])

    await message.reply(text, reply_markup=InlineKeyboardMarkup(rows))


# ─────────────────────────────────────────────
# 👥 GROUP REGISTRY (Bot Admin only, PM)
# ─────────────────────────────────────────────
@Client.on_message(filters.command(["add_group"]) & filters.user(ADMINS) & filters.private)
async def add_group_cmd(client, message):
    """Group ko register karta hai → mode = FILTER (auto-filter chalu).

    Usage: ``/add_group -1001234567890``
    """
    if len(message.command) < 2:
        return await message.reply(
            "⚠️ <b>Usage:</b> <code>/add_group &lt;chat_id&gt;</code>\n"
            "💡 Group ID Telegram se milegi (ya bot ko group me add karke uska ID copy karein)."
        )

    raw = message.command[1].strip()
    try:
        chat_id = int(raw)
    except ValueError:
        return await message.reply("❌ Chat ID numeric honi chahiye (jaise <code>-1001234567890</code>).")

    title = " ".join(message.command[2:]).strip()

    # Title verify karne ki koshish (bot group me hai ya nahi)
    if not title:
        try:
            chat = await client.get_chat(chat_id)
            title = chat.title or "Unknown"
            me = await client.get_me()
            member = await client.get_chat_member(chat_id, me.id)
            if member.status.value in ("left", "banned"):
                await message.reply(
                    "⚠️ Bot abhi is group me <b>member nahi</b> hai — register to ho gaya, "
                    "par auto-filter tabhi chalega jab bot add ho jaye."
                )
        except Exception:
            title = "Unknown"

    await db.add_chat(chat_id, title)
    await set_group_mode(chat_id, MODE_FILTER)

    try:
        await client.send_message(
            chat_id,
            script.GROUP_REGISTERED_TXT.format(title, chat_id),
        )
    except Exception as e:
        logger.debug(f"add_group notify failed: {e}")

    await message.reply(
        f"✅ <b>Group registered!</b>\n\n"
        f"👥 <b>{title}</b>\n"
        f"🆔 ID: <code>{chat_id}</code>\n"
        f"🎬 Mode: <b>Auto Filter (FILTER)</b>\n\n"
        f"ℹ️ Is group me ab auto-filter chalega; group-manager features dormant rahengi."
    )

    if LOG_CHANNEL:
        try:
            await client.send_message(
                LOG_CHANNEL,
                f"#GroupRegistered\n👥 <code>{title}</code>\n🆔 <code>{chat_id}</code>\n🎬 Mode: FILTER")
        except Exception:
            pass


@Client.on_message(filters.command(["rm_group"]) & filters.user(ADMINS) & filters.private)
async def rm_group_cmd(client, message):
    """Group ka auto-filter registration hata deta hai → mode = MANAGEMENT."""
    if len(message.command) < 2:
        return await message.reply("⚠️ <b>Usage:</b> <code>/rm_group &lt;chat_id&gt;</code>")

    try:
        chat_id = int(message.command[1].strip())
    except ValueError:
        return await message.reply("❌ Chat ID numeric honi chahiye.")

    await set_group_mode(chat_id, MODE_MGMT)
    await message.reply(
        f"✅ <b>Group un-registered!</b>\n\n"
        f"🆔 ID: <code>{chat_id}</code>\n"
        f"🛡️ Mode: <b>Group Manager (MANAGEMENT)</b>\n\n"
        f"ℹ️ Ab is group me auto-filter nahi chalega — sirf group-manager features."
    )


@Client.on_message(filters.command(["set_gmode"]) & filters.user(ADMINS) & filters.private)
async def set_gmode_cmd(client, message):
    """Group ka mode manually set karta hai — ``/set_gmode <id> filter|management``"""
    if len(message.command) < 3:
        return await message.reply(
            "⚠️ <b>Usage:</b> <code>/set_gmode &lt;chat_id&gt; filter|management</code>")

    try:
        chat_id = int(message.command[1].strip())
    except ValueError:
        return await message.reply("❌ Chat ID numeric honi chahiye.")

    mode = normalize_mode(message.command[2])
    if not mode:
        return await message.reply("❌ Mode <code>filter</code> ya <code>management</code> hona chahiye.")

    await set_group_mode(chat_id, mode)
    label = "🎬 Auto Filter" if mode == MODE_FILTER else "🛡️ Group Manager"
    await message.reply(f"✅ <code>{chat_id}</code> ka mode ab <b>{label}</b> hai.")


@Client.on_message(filters.command(["list_groups"]) & filters.user(ADMINS) & filters.private)
async def list_groups_cmd(client, message):
    """Sabhi registered groups + unka live mode (+ user-mode ka breakdown)."""
    # ✅ DRY: group list + mode resolution modes.list_group_modes() se aata hai
    # (legacy groups bina mode field ke bhi FILTER hi dikhte hain, jaisa
    # runtime par behave karte hain).
    groups = await list_group_modes()

    if not groups:
        return await message.reply("📭 Abhi koi group registered nahi hai.")

    filter_count = sum(1 for g in groups if g["mode"] == MODE_FILTER)
    mgmt_count = len(groups) - filter_count

    rows = []
    for g in groups[:60]:
        icon = "🎬" if g["mode"] == MODE_FILTER else "🛡️"
        rows.append(f"{icon} <b>{esc(g['title'])}</b>\n   🆔 <code>{g['id']}</code> — {g['mode']}")

    users_filter = await db.total_mode_users_count(MODE_FILTER)
    users_mgmt = await db.total_mode_users_count(MODE_MGMT)

    text = (
        f"👥 <b>Registered Groups</b> (<code>{len(groups)}</code>)\n"
        f"🎬 Auto Filter: <code>{filter_count}</code> • 🛡️ Group Manager: <code>{mgmt_count}</code>\n\n"
        + "\n".join(rows)
        + f"\n\n🧠 <b>User modes chosen:</b> 🎬 <code>{users_filter}</code> • 🛡️ <code>{users_mgmt}</code>"
    )
    await message.reply(text)
