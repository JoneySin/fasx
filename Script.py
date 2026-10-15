class script(object):

    # 🍿 आपके लाइव फीचर्स और प्रीमियम मॉडल के अनुसार स्टार्ट टेक्स्ट (DM locked logic ready)
    START_TXT = """<blockquote><b><i>Hey {}, {}</i></b></blockquote>
<blockquote><b><i>I am a powerful & smart auto filter bot! I can provide movies and series with direct stream & download links. 🚀</i></b></blockquote>

🍿 <b><u>My Main Features:</u></b>

<blockquote><b><i>Smart Auto Filter In Chat Groups</i></b></blockquote>
<blockquote><b><i>📱 Advanced Mini App Cinematic Search</i></b></blockquote>
<blockquote><b><i>🎬 In-Built Player With Double-Tap Skip</i></b></blockquote>
<blockquote><b><i>⚡ Superfast Direct Download Links</i></b></blockquote>
<blockquote><b><i>🛡️ Auto Delete Queue (Restart Proof)</i></b></blockquote>
<blockquote><b><i>✨ Join Premium For Ads Free Experience</i></b></blockquote>"""

    # 📊 ✅ NEW PREMIUM UI: एकदम नया मॉडर्न लुक जिसमें Directory भी शामिल है (Admin Only)
    STATUS_TXT = """<b>🤖 Fast Finder System Telemetry</b>

<b>👥 <u>Network Dynamics:</u></b>
<blockquote><b>🤵 Users:</b> <code>{}</code>
<b>🏘️ Groups:</b> <code>{}</code>
<b>💎 Premium:</b> <code>{}</code></blockquote>

<b>🗄️ <u>Data Centre (Total: {}):</u></b>
<blockquote><b>🟢 Primary:</b> <code>{}</code> (🖼️ <code>{}</code>)
<b>🔵 Cloud:</b> <code>{}</code> (🖼️ <code>{}</code>)
<b>🟠 Archive:</b> <code>{}</code> (🖼️ <code>{}</code>)</blockquote>

<b>🗂️ <u>Universal Directory (Total: {}):</u></b>
<blockquote><b>🎭 Actors:</b> <code>{}</code>
<b>📱 Apps:</b> <code>{}</code>
<b>🌐 Websites:</b> <code>{}</code></blockquote>

<b>📝 <u>Posts CMS (Total: {}):</u></b>
<blockquote><b>🎬 Movies:</b> <code>{}</code>
<b>📺 Web Series:</b> <code>{}</code>
<b>📱 App Video:</b> <code>{}</code>
<b>🔞 Porn:</b> <code>{}</code></blockquote>

<b>⚙️ <u>Engine Metrics:</u></b>
<blockquote><b>🖼️ Global Thumbs:</b> <code>{}</code>
<b>⏱️ Uptime:</b> <code>{}</code></blockquote>"""

    # ✅ सिर्फ प्रीमियम/नॉर्मल यूज़र्स के लिए ग्लोबल लाइब्रेरी स्टैट्स
    USER_STATUS_TXT = """<b>📊 Fast Finder Global Library</b>

<b>🗄️ <u>Content Vault:</u></b>
<blockquote><b>🚀 Total Titles:</b> <code>{}</code>
<b>🟢 Primary:</b> <code>{}</code>
<b>🔵 Cloud:</b> <code>{}</code>
<b>🟠 Archive:</b> <code>{}</code></blockquote>

<b>🗂️ <u>Universal Directory:</u></b>
<blockquote><b>🌟 Total Profiles:</b> <code>{}</code>
<b>🎭 Actors:</b> <code>{}</code>
<b>📱 Apps:</b> <code>{}</code>
<b>🌐 Websites:</b> <code>{}</code></blockquote>

<b>📝 <u>Posts Published:</u></b> <code>{}</code>

<b>⏱️ System Running Since:</b> <code>{}</code>"""

    NEW_GROUP_TXT = """<b>#NewGroup 👥\n\n• Title: {}\n• ID: <code>{}</code>\n• Username: {}\n• Total Members: <code>{}</code></b>"""

    # ══════════════════════════════════════════════════════════════
    # 🛡️ MULTI-BOT — GROUP MANAGER SIDE TEXTS
    # ══════════════════════════════════════════════════════════════

    # 🎬 /start par mode-choice screen (sirf Admin + Premium users ko dikhta hai)
    MODE_PICK_TXT = """<blockquote><b><i>Hey {}, {}</i></b></blockquote>
<blockquote><b><i>Main ek hi code-base se do bots chalata hoon — aap apna mode chuno:</i></b></blockquote>

🎬 <b><u>Auto Filter Bot:</u></b>
<blockquote><i>Group me search, direct stream & download links, mini app.</i></blockquote>

🛡️ <b><u>Group Manager Bot:</u></b>
<blockquote><i>Blacklist, link & media block, language filter, warn, ban, mute, admin-tag report.</i></blockquote>

<blockquote><b>⚠️ Aapka choice permanent rahega — baad me <code>/mode</code> se badal sakte ho.</b></blockquote>"""

    # 🛡️ Group-Manager mode ka PM start text (free + premium dono ke liye)
    GM_START_TXT = """<blockquote><b><i>Hey {}, {}</i></b></blockquote>
<blockquote><b><i>Main ek powerful <b>Group Manager Bot</b> hoon! Apne group ko spam-free aur safe rakhne ke liye sab tools. 🛡️</i></b></blockquote>

🛡️ <b><u>My Group Manager Features:</u></b>

<blockquote><b><i>🚫 Blacklist Words & Links</i></b></blockquote>
<blockquote><b><i>🌍 Language Filter (auto-detect)</i></b></blockquote>
<blockquote><b><i>🖼 Block Media (photo / video / sticker / forward…)</i></b></blockquote>
<blockquote><b><i>⚠️ Warn System + Auto Ban</i></b></blockquote>
<blockquote><b><i>🚨 Report with Admin Tagging</i></b></blockquote>
<blockquote><b><i>🔇 Mute / 🔪 Kick / 🧹 Purge / 🔒 Lock / 🐢 Slowmode</i></b></blockquote>
<blockquote><b><i>🌊 Antiflood (auto mute + warn)</i></b></blockquote>

<blockquote><b>📌 Group me add karne ke baad <code>/gm</code> command se control panel khol sakte ho.</b></blockquote>"""

    # 🛡️ Feature detail page (PM)
    GM_FEATURES_TXT = """<b>🛡️ Group Manager — Full Feature List</b>

<blockquote><b><u>🚫 Content Filtering</u></b>
• Blacklisted words (case-insensitive)
• Blocked links / domains + whitelist
• Blocked media types (photo, video, document, sticker, voice, animation, forward)
• Language filter (Unicode-script auto-detect)
</blockquote>

<blockquote><b><u>⚠️ Moderation</u></b>
• Warn system with auto-ban limit
• Ban / Unban, Mute / Unmute, Kick
• Bulk purge (reply-based), Lock / Unlock chat
• Slow mode (seconds)
• Antiflood — message-rate guard (auto mute + warn)
</blockquote>

<blockquote><b><u>🚨 Reporting</u></b>
• Reply + <code>/report</code> → admins tagged instantly
• Quick actions: Ban / Warn / Delete / Dismiss
• Audit copy bot-owner ke log channel me
</blockquote>

<blockquote><b>📌 Ye sab features tabhi chalti hain jab group <b>Group Manager mode</b> me ho. Auto Filter mode wale groups me auto-filter chalta hai.</b></blockquote>"""

    # 🛡️ PM help (group-manager user ke liye)
    GM_HELP_TXT = """<b>📘 Group Manager — Help</b>

<blockquote><b><u>👥 Group Admin Commands (group me):</u></b>
• /gm — Control panel (manager on-off toggle, limits, lists)
• /addword <word> • /rmword <word> • /words
• /addlink <domain> • /rmlink <domain> • /links
• /allowlink <domain> • /rmallow <domain>
• /blockmedia <types> • /unblockmedia <types>
• /setlang hi,en • /langs • /offlang
• /warn [reason] • /warnings • /resetwarn • /setwarnlimit <n>
• /ban • /unban • /mute • /unmute • /kick
• /purge • /lock • /unlock • /slowmode <sec> • /banlist
• /antiflood <limit> <window> • /antiflood off — flood guard
</blockquote>

<blockquote><b><u>💬 Any Member:</u></b>
• /report [reason] — message par reply karke admins ko report karein
</blockquote>

<blockquote><b>🔁 Mode switch: <code>/mode</code> command ya "🔄 Switch Bot Mode" button.</b></blockquote>"""

    # 🛡️ Group admins ke liye command list (help panel me dikhta hai)
    GM_ADMIN_COMMAND_TXT = """<blockquote><b>🛡️ <u>Group Manager Commands:</u> 👇</b></blockquote>

• /gm - Control panel
• /addword <word> - Blacklist word add
• /rmword <word> - Blacklist word remove
• /words - Blacklist words list
• /addlink <domain> - Block a link
• /rmlink <domain> - Unblock a link
• /links - Link filter status
• /allowlink <domain> - Whitelist a link
• /rmallow <domain> - Remove whitelist
• /blockmedia <types> - Block media types
• /unblockmedia <types> - Unblock media types
• /setlang <codes> - Set allowed languages
• /langs - Language filter status
• /offlang - Disable language filter
• /warn [reason] - Warn a user
• /warnings - Warning count
• /resetwarn - Reset warnings
• /setwarnlimit <n> - Auto-ban limit
• /ban [reason] - Ban a user
• /unban - Unban a user
• /mute - Mute a user
• /unmute - Unmute a user
• /kick - Kick a user
• /purge - Bulk delete messages
• /lock - Lock the chat
• /unlock - Unlock the chat
• /slowmode <sec> - Set slow mode
• /banlist - Banned users list
• /antiflood <limit> <window> - Flood guard (messages per window)
• /report - Report a message (any member)"""

    # 🧠 Mode switch status
    MODE_SWITCHED_TXT = """✅ <b>Mode switched!</b>

🎬 Ab aap <b>Auto Filter Bot</b> use kar rahe hain — group me search, mini app aur streaming.
🛡️ Group manager features ke liye <code>/mode</code> se wapas switch kar sakte ho."""

    MODE_SWITCHED_GM_TXT = """✅ <b>Mode switched!</b>

🛡️ Ab aap <b>Group Manager Bot</b> use kar rahe hain — blacklist, warn, ban, report aur puri group protection.
🎬 Auto filter ke liye <code>/mode</code> se wapas switch kar sakte ho."""

    # 🛡️ Mode info (PM)
    MODE_INFO_TXT = """<b>🧠 Aapka Bot Mode</b>

🎬 <b>Auto Filter Bot</b> — search, mini app, direct stream & download
🛡️ <b>Group Manager Bot</b> — blacklist, warn, ban, mute, report, moderation

📌 <b>Current:</b> {}
🔄 Switch karne ke liye neeche button dabayein."""

    # 📢 Group mode explainer (group me bot add hone par)
    GROUP_START_GM_TXT = """<b>Hey {}, <i>I am your Group Manager Bot</i> 🛡️</b>

<blockquote><i>Is group me auto-filter <b>OFF</b> hai — main yahan spam, links, unwanted media aur wrong-language messages rokhta hoon.</i></blockquote>

📌 <b>Group Admin:</b> control panel kholne ke liye <code>/gm</code> likhein.
🚨 <b>Any Member:</b> kisi message par reply karke <code>/report</code> likhein — admins ko turant tag ho jayenge.

🔄 <b>Auto Filter chahiye?</b> Bot admin ko is group ka ID apne bot ke PM me <code>/add_group</code> se register karna hoga."""

    GROUP_ADDED_GM_TXT = """👋 <b>Hello {},

Thanks for adding me to {}!</b>

🛡️ <b>Main abhi <u>Group Manager Bot</u> mode me hoon.</b>
<blockquote><i>Is group me auto-filter OFF hai. Meri kaam-khari: blacklist, link & media block, language filter, warn, ban, mute aur admin-tag report.</i></blockquote>

📌 <b>Control panel kholne ke liye:</b> <code>/gm</code>
🔄 <b>Auto Filter chahiye?</b> Bot admin ko is group ka ID apne bot ke PM me <code>/add_group</code> se register karna hoga.

⚠️ <i>Please grant me admin rights with "Delete Messages" permission.</i>"""

    # 📢 Group add hone par (jab group pehle se FILTER ke liye registered hai)
    GROUP_ADDED_FILTER_TXT = """👋 <b>Hello {},

Thanks for adding me to {}!</b>

🎬 <b>Ye group <u>Auto Filter Bot</u> mode me hai.</b>
<blockquote><i>Members movie/series ka naam type karke direct stream &amp; download links pa sakte hain. Group-manager features is group me dormant rehte hain.</i></blockquote>

📌 <b>Search:</b> koi bhi movie / series ka naam type karein.
⚠️ <i>Please grant me admin rights with "Delete Messages" permission.</i>"""

    # 📢 Group mode explainer (admin ne PM se register kiya)
    GROUP_REGISTERED_TXT = """✅ <b>Auto Filter Mode activated!</b>

🎬 Ab is group me auto-filter chalta hai — search, direct stream & download links.
🛡️ <i>Group-manager features is group me dormant rahengi (dono ek saath nahi chalti).</i>

📌 Group: <b>{}</b>
🆔 ID: <code>{}</code>"""

    NEW_USER_TXT = """<b>#NewUser 👤\n\n• Name: {}\n• ID: <code>{}</code></b>"""

    NOT_FILE_TXT = """<b>❌ Hey {}, "{}" is not found in my database. 

💡 <u>Please Check:</u>
» Spelling should be correct (check Google)
» Search with movie name only ( things like 4k, Bluray, Season, Year हटा दें)</b>"""

    FILE_CAPTION = """<b>{file_name}</b>"""

    WELCOME_TEXT = """👋 Hello {mention}, Welcome to {title} group! 💞"""

    HELP_TXT = """<blockquote><b>👋 Hello {},</b></blockquote>

<b>Fast. Smart. Powerful.

Choose a category below. 👇</b>"""

    ADMIN_COMMAND_TXT = """<blockquote><b>👑 <u>Bot Admin Commands:</u> 👇</b></blockquote>

• /stats - Database stats
• /delete - Delete file
• /delete_all - Clear collection
• /add_prm - Add premium
• /rm_prm - Remove premium
• /prm_list - Premium users
• /web_users - Web users
• /warmup_thumbs - Refresh thumbnails
• /migrate_meta - Probe true resolution, fill missing meta &amp; fix file types
• /restart - Restart bot
• /users - Export users.txt backup
• /chats - Export chats.txt backup

<blockquote><b>🧠 <u>Multi-Bot (Group Registry):</u> 👇</b></blockquote>

• /add_group &lt;chat_id&gt; - Register group in Auto Filter mode
• /rm_group &lt;chat_id&gt; - Unregister group (back to Group Manager mode)
• /set_gmode &lt;chat_id&gt; &lt;filter|management&gt; - Set group mode manually
• /list_groups - List all groups with their live mode

<blockquote><b>🛠️ <u>Bot Maintenance:</u> 👇</b></blockquote>

• /leave &lt;chat_id&gt; - Leave a chat
• /invite_link &lt;chat_id&gt; - Generate invite link
• /ban_grp | /unban_grp &lt;id&gt; [reason] - Ban / unban a group
• /ban_user | /unban_user &lt;id&gt; [reason] - Ban / unban a user
• /check_db - Primary → cloud migration check
• /cancel - Cancel a running /check_db

<blockquote><b>⚙️ <u>Group Commands:</u> 👇</b></blockquote>

• /search - Auto Filter
• /settings - Group settings
• /button_style - Result style
• /gm - Group Manager control panel"""
    
    PLAN_TXT = """💎 <b>Fast Finder Premium Plans</b> 💎

Activate a premium plan to unlock exclusive, high-speed features!

⚡ <b>Price:</b> <code>₹{} / Per Day</code> ⚡

🚀 <b>Premium Features Include:</b>
» 🍿 Ad-Free Experience (No interruptions)
» 🎬 Online Streaming & Superfast Downloads
» 🔓 No Need to Join Extra Channels (No FSUB)
» ⚡ Zero Verification / Shortlinks Required
» 👑 Dedicated Admin Support

👨‍🚒 <b>Support & Verification:</b> {}"""

    USER_COMMAND_TXT = """<blockquote><b>👨‍💻 <u>Bot User Commands:</u> 👇</b></blockquote>

• /start - Main menu
• /mode - Switch bot mode (Auto Filter / Group Manager)
• /plan - Premium plans
• /myplan - Premium status
• /id - User & Chat ID
• /link - Watch & Download link (reply to media, Premium)"""

    LOG_INDEX_TXT = """📢 <b>#Indexing_Report 📊</b>

<b>📂 Storage Parameters:</b>
» Chat Title: <code>{}</code>
» Chat ID: <code>{}</code>
» Collection Targeted: <code>{}</code>

<b>📈 Execution Statistics:</b>
» Total Processed: <code>{}</code> Files
» Successfully Saved: <code>{}</code> Files
» Duplicates Skipped: <code>{}</code> Files
» Unsupported Format: <code>{}</code> Files
» Errors Intercepted: <code>{}</code> Files

<b>⏱️ Engine Performance:</b>
» Status: <code>Completed Successfully ✅</code>
» Triggered By: <code>Authorized Bot Admin 👮‍♂️</code>"""
