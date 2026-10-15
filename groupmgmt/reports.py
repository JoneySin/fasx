"""
🚨 REPORT ENGINE (Group Manager)
================================

Group me koi bhi member kisi message ko report kar sakta hai — bot us
message ko **group ke admins ko tag** karke ek report card bhejta hai
(aur message delete kar deta hai, taaki spam turant hata ho).

Report card par quick-action buttons:
• 🔨 Ban     — user ko turant ban
• ⚠️ Warn   — user ko warning
• 🗑 Delete  — reported message delete
• ✅ Dismiss — report par action nahi

Saath hi bot-owner ke LOG_CHANNEL me bhi ek copy jaata hai (audit trail).
"""

import logging

from hydrogram import Client, filters

from groupmgmt.core import (
    S_DELETE, add_warn, ban_member, build_admin_mentions, delete_message, esc,
    get_gm_settings, gm_enabled, is_admin, reset_warn,
)
from info import ADMINS, LOG_CHANNEL

logger = logging.getLogger(__name__)


async def _report_target(message):
    """Report kis message ki hai — reply ka message ya khud ka."""
    return message.reply_to_message or message


@Client.on_message(filters.command(["report"]) & filters.group)
async def report_cmd(client, message):
    """Kisi message ko report karta hai — admins ko tag karke."""
    if not await gm_enabled(message.chat.id):
        return await message.reply(
            "ℹ️ Ye group <b>Auto Filter mode</b> me hai — group-manager features "
            "yahan active nahi hain."
        )

    target_msg = await _report_target(message)
    reported_user = target_msg.from_user
    reason = " ".join(message.command[1:]).strip() if len(message.command) > 1 else ""
    if not reason:
        reason = "Spam / Rule violation"

    if not reported_user:
        return await message.reply("⚠️ Report ke liye kisi message par reply karein.")

    mentions = await build_admin_mentions(client, message.chat.id)
    if not mentions:
        return await message.reply("❌ Is group me koi admin nahi mila — report nahi bhej sakta.")

    settings = await get_gm_settings(message.chat.id)

    report_text = (
        f"{mentions}\n\n"
        f"🚨 <b>REPORT</b>\n"
        f"👤 Reported: {reported_user.mention} (<code>{reported_user.id}</code>)\n"
        f"🗣 Reason: <code>{esc(reason[:150])}</code>\n"
        f"💬 Message: <a href='tg://openmessage?chat_id={message.chat.id}&message_id={target_msg.id}'>jump →</a>\n"
        f"🕐 Time: <code>{message.date.strftime('%d %b %Y, %I:%M %p')}</code>"
    )

    btn = [
        [
            {"text": "🔨 Ban", "callback_data": f"gm_rep#ban#{message.chat.id}#{reported_user.id}#{target_msg.id}"},
            {"text": "⚠️ Warn", "callback_data": f"gm_rep#warn#{message.chat.id}#{reported_user.id}#{target_msg.id}"},
        ],
        [
            {"text": "🗑 Delete Msg", "callback_data": f"gm_rep#del#{message.chat.id}#{reported_user.id}#{target_msg.id}"},
            {"text": "✅ Dismiss", "callback_data": f"gm_rep#dismiss#{message.chat.id}#{reported_user.id}#{target_msg.id}"},
        ],
    ]

    from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in row]
        for row in btn
    ])

    sent = await message.reply(report_text, reply_markup=markup)

    if settings.get(S_DELETE, True):
        await delete_message(client, message.chat.id, target_msg.id)

    # Bot-owner ke log channel me audit copy
    if LOG_CHANNEL:
        try:
            await client.send_message(
                LOG_CHANNEL,
                f"#GroupReport\n👥 Group: <code>{esc(message.chat.title)}</code> "
                f"(<code>{message.chat.id}</code>)\n"
                f"👤 Reported: {reported_user.mention} (<code>{reported_user.id}</code>)\n"
                f"🗣 Reason: <code>{esc(reason[:150])}</code>\n"
                f"🔗 Report: https://t.me/c/{str(message.chat.id).replace('-100', '')}/{target_msg.id}",
            )
        except Exception as e:
            logger.debug(f"report log failed: {e}")

    return sent


@Client.on_callback_query(filters.regex(r"^gm_rep#"))
async def report_action_cb(client, query):
    """Report card ke quick-action buttons."""
    try:
        parts = query.data.split("#")
        action = parts[1]
        chat_id = int(parts[2])
        user_id = int(parts[3])
        msg_id = int(parts[4])
    except Exception:
        return await query.answer("❌ Invalid report data.", show_alert=True)

    # Sirf group admins hi action le sakte hain
    try:
        if not await is_admin(client, chat_id, query.from_user.id):
            return await query.answer("❌ Sirf group admins ye action le sakte hain.", show_alert=True)
    except Exception:
        return await query.answer("❌ Action failed.", show_alert=True)

    try:
        target_user = await client.get_users(user_id)
        name = esc(target_user.first_name or "User")
    except Exception:
        target_user = None
        name = f"<code>{user_id}</code>"

    if action == "ban":
        if user_id in ADMINS:
            return await query.answer("❌ Bot admin ko ban nahi kar sakte.", show_alert=True)
        ok = await ban_member(client, chat_id, user_id, "Reported by admin")
        await query.answer("🔨 Ban ho gaya." if ok else "❌ Ban fail.", show_alert=True)
        try:
            await query.message.edit_text(
                f"🚨 <b>REPORT</b>\n\n🔨 <b>{name}</b> ko ban kar diya gaya "
                f"(by {query.from_user.mention}).")
        except Exception:
            pass
        return

    if action == "warn":
        count, limit = await add_warn(chat_id, user_id, "Reported by admin")
        await query.answer(f"⚠️ Warning {count}/{limit}", show_alert=True)
        try:
            await client.send_message(
                chat_id, f"⚠️ <b>{name}</b> ko warning di gayi.\n🔢 <code>{count}/{limit}</code>")
        except Exception:
            pass
        if limit > 0 and count >= limit:
            await ban_member(client, chat_id, user_id, "Auto-ban (report warnings)")
            await reset_warn(chat_id, user_id)
        return

    if action == "del":
        await delete_message(client, chat_id, msg_id)
        await query.answer("🗑 Message delete ho gaya.", show_alert=True)
        return

    if action == "dismiss":
        await query.answer("✅ Report dismiss.", show_alert=True)
        try:
            await query.message.edit_text(
                f"🚨 <b>REPORT</b>\n\n✅ Dismissed by {query.from_user.mention}.")
        except Exception:
            pass
        return

    await query.answer("❌ Unknown action.", show_alert=True)
