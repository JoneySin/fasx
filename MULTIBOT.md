# 🧠 Multi-Bot Guide (Auto Filter + Group Manager)

Is ek code-base se **do bots** chalte hain — dono ka apna mode, apna menu aur
apne bahav:

| | 🎬 Auto Filter Bot | 🛡️ Group Manager Bot |
|---|---|---|
| **Kya karta hai** | Group me search, direct stream & download, Mini App | Blacklist, link/media/language block, warn, ban, mute, report, antiflood |
| **Kaun use karta hai** | Premium users (PM search) + FILTER-mode groups | Free / public users + MGMT-mode groups |
| **Code kahan hai** | `plugins/` (+ `web/` Mini App) | `groupmgmt/` folder |

---

## 1. 👤 User Mode (PM behaviour)

`/start` (PM) par:

| User | Kya dikhta hai |
|---|---|
| 👑 Bot Admin / 💎 Premium (pehli baar) | **Choice screen** — 🎬 Auto Filter ya 🛡️ Group Manager. Jo button dabayega, wahi uska **permanent** mode ban jayega. |
| ✅ Admin / Premium (mode chun chuka) | Usi mode ka menu (baad me badalna ho to `/mode`) |
| 👤 Free / Public user | **Group Manager menu** + niche **💎 Join Premium** button (mode switch premium-only hai) |

Mode `UserModes` collection me save hota hai (`db.get_user_mode` / `set_user_mode`).
Mode ke hisaab se PM search ka behaviour bhi badalta hai:
Group-Manager mode wale user ka PM search nahi chalta (auto-filter premium-gated
hai) — usse "Switch Bot Mode" button milta hai.

## 2. 👥 Group Mode (group behaviour)

| Kab | Mode | Matlab |
|---|---|---|
| Bot manually kisi **group me ADD** hota hai | 🛡️ **MANAGEMENT** | Us group me **auto-filter chalega hi nahi** — sirf group-manager features |
| Bot-admin PM se **`/add_group <chat_id>`** karta hai | 🎬 **FILTER** | Us group me **auto-filter chalta hai** (search, streaming links) |

* Mode `Groups.mode` field me save hota hai (TTL cache ke saath — `modes.py`).
* Purane (legacy) auto-filter groups jinka `mode` field nahi hai, wo **FILTER**
  hi rehte hain — deploy karne par unka behaviour nahi tootta.
* Group pehle se auto-filter ke liye registered hai, aur bot dobara add hota hai
  to admin ka decision override **nahi** hota (`modes.ensure_mode_after_bot_add`).

### Bot-Admin commands (PM)

```
/add_group <chat_id>            # register → FILTER mode (auto filter ON)
/rm_group <chat_id>             # unregister → MANAGEMENT mode
/set_gmode <chat_id> <mode>     # filter | management
/list_groups                    # sabhi groups + unka live mode + user-mode stats
```

---

## 3. 🛡️ Group Manager Features (`groupmgmt/`)

| Module | Kya deta hai | Commands |
|---|---|---|
| `blacklist.py` | Word / link / media blocking | `/addword` `/rmword` `/words` `/addlink` `/rmlink` `/links` `/allowlink` `/rmallow` `/blockmedia` `/unblockmedia` |
| `language.py` | Unicode-script language filter (23 languages) | `/setlang hi,en` `/langs` `/offlang` |
| `moderation.py` | Warn → auto-ban, ban/mute/kick, purge, lock, slowmode | `/warn` `/warnings` `/resetwarn` `/setwarnlimit` `/ban` `/unban` `/mute` `/unmute` `/kick` `/purge` `/lock` `/unlock` `/slowmode` `/banlist` |
| `antiflood.py` | Message-rate guard (auto mute + warn) | `/antiflood 5 10` `/antiflood off` |
| `reports.py` | Reply + `/report` → group admins **tag** ho kar report card milta hai (Ban / Warn / Delete / Dismiss buttons) | `/report` |
| `menu.py` | Group control panel + PM menu | `/gm` (group admins) |
| `core.py` | Shared helpers (mode-gate, warn/ban/mute, admin mentions, violation handler) | — |

### Group Control Panel (`/gm` — sirf group admins)

Inline buttons se live control: manager ON/OFF, delete-on-violation ON/OFF,
warn limit +/- , aur saare block-lists (words / links / allowed / media /
languages / banned users) ki live status.

### Violation flow

`blacklist / link / media / language / antiflood` violation par:

1. 🗑 Message delete (agar `delete_on_violation` ON hai)
2. ⚠️ Warning + notice
3. 🔨 Limit cross → **auto-ban** + warnings reset
4. 👮 Group admins aur bot-admins ko kabhi touch nahi karte

---

## 4. 🔒 Mutual Exclusion (zaroori rule)

| Group mode | Auto filter | Group management |
|---|---|---|
| 🎬 FILTER | ✅ chalta hai | ❌ dormant |
| 🛡️ MANAGEMENT | ❌ **chalega hi nahi** | ✅ chalta hai |

Isi tarah `/search`, `/button_style`, `/settings` MGMT group me filter-settings
ke bajaye **manager panel** dikhate hain.

---

## 5. ⚙️ Settings (per-group, `Groups.settings`)

| Key | Default | Kaam |
|---|---|---|
| `mgmt_enabled` | `True` | Group manager features ka master switch |
| `blacklist` | `[]` | Blocked words |
| `block_links` / `allow_links` | `[]` | Blocked / whitelisted domains |
| `block_media` | `[]` | Blocked media types (`photo`, `video`, `document`, `sticker`, `voice`, `animation`, `forward`, …) |
| `allowed_langs` | `[]` | Allowed languages (`[]` = filter OFF) |
| `warn_limit` | `3` | Auto-ban warning limit (`0` = kabhi auto-ban nahi) |
| `delete_on_violation` | `True` | Violating message delete karna hai ya nahi |
| `banned_users` / `muted_users` | `{}` | Per-group lists |
| `antiflood` | `{"limit": 0, "window": 10}` | `limit = 0` → OFF |

---

## 6. 🧩 Architecture Notes

* `modes.py` — mode engine (single source of truth) + 60s TTL cache + "kaun sa
  group kaunsa mode" decide karne ki saari logic.
* `plugins/multibot.py` — PM mode menus, `/mode`, group registry commands.
* `groupmgmt/` — group-manager features ka **alag folder**; bot.py ise extra
  plugin-root ke taur par load karta hai (`EXTRA_PLUGIN_ROOTS`) kyunki hydrogram
  ka loader sirf ek root support karta hai.
* `bot.py` ke `Bot.load_plugins()` override se dono roots load hote hain —
  standard `plugins/` pehle, phir `groupmgmt/`.

## 7. 🧪 Tests

```bash
python -m unittest discover -s tests          # 259 tests
```

* `tests/test_multibot.py` — mode engine, user/group mode rules, blacklist
  matchers, language detection, violation flow, antiflood, mutual exclusion.
* `tests/test_core.py` — command-list ↔ handler sync ab dono plugin roots
  (`plugins/` + `groupmgmt/`) ko scan karta hai.
