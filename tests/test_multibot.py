"""
🧠 MULTI-BOT regression tests.

Ye suite us poore "ek bot, do personality" behaviour ko cover karti hai jo
user ne maanga tha:

1. 👤 USER MODE — Admin/Premium ko pehli /start par choice (Auto Filter vs
   Group Manager); free user ko default Group Manager + premium button.
   Choice permanent (DB me save).
2. 👥 GROUP MODE — bot group me ADD hone par MANAGEMENT (auto-filter OFF),
   aur bot-admin ke PM se /add_group karne par FILTER (auto-filter ON).
3. 🚫 GROUP MANAGER features — blacklist (words/links/media), language
   filter, warn/ban/mute, report.
4. 🔒 Mutual exclusion — MGMT group me auto-filter nahi chalta, FILTER group
   me group-manager enforcement nahi chalta.

Run:  python -m unittest discover -s tests -v
"""
import asyncio
import os
import sys
import unittest
from unittest import mock

# ── info.py ko import-time validation se bachane ke liye env stubs ──
os.environ.setdefault("API_ID", "123456")
os.environ.setdefault("API_HASH", "test_hash")
os.environ.setdefault("BOT_TOKEN", "123456:test_token")
os.environ.setdefault("ADMINS", "111 222")
os.environ.setdefault("LOG_CHANNEL", "-1001234567890")
os.environ.setdefault("BIN_CHANNEL", "-1009876543210")
os.environ.setdefault("DATABASE_URL", "mongodb://localhost:27017")
os.environ.setdefault("DATABASE_NAME", "testdb")
os.environ.setdefault("URL", "https://example.com")
os.environ.setdefault("TIME_ZONE", "Asia/Kolkata")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hydrogram import enums  # noqa: E402

import modes  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _reset_mode_cache():
    modes.invalidate_cache()


class TestModeNormalize(unittest.TestCase):
    """Modernaize — har alias canonical mode par map ho."""

    def test_filter_aliases(self):
        for raw in ("filter", "FILTER", " autofilter ", "auto_filter", "auto",
                    "search", "movie"):
            with self.subTest(raw=raw):
                self.assertEqual(modes.normalize_mode(raw), modes.MODE_FILTER)

    def test_management_aliases(self):
        for raw in ("management", "Group", "MGMT", "group_manager", "moderation"):
            with self.subTest(raw=raw):
                self.assertEqual(modes.normalize_mode(raw), modes.MODE_MGMT)

    def test_invalid_gives_none(self):
        for raw in (None, "", "   ", "premium", 5, [], {"a": 1}):
            with self.subTest(raw=raw):
                self.assertIsNone(modes.normalize_mode(raw))

    def test_defaults(self):
        # Group me bot add hone par = MANAGEMENT, aur free user ka default bhi
        self.assertEqual(modes.DEFAULT_GROUP_MODE, modes.MODE_MGMT)
        self.assertEqual(modes.DEFAULT_FREE_USER_MODE, modes.MODE_MGMT)


class TestUserMode(unittest.TestCase):
    """User mode DB save + cache."""

    def setUp(self):
        _reset_mode_cache()

    def test_get_when_never_chosen(self):
        with mock.patch.object(modes.db, "get_user_mode", new=mock.AsyncMock(return_value=None)):
            self.assertIsNone(run(modes.get_user_mode(500)))

    def test_set_then_get_uses_cache(self):
        setter = mock.AsyncMock()
        with mock.patch.object(modes.db, "set_user_mode", new=setter):
            self.assertTrue(run(modes.set_user_mode(501, "filter")))
        setter.assert_awaited_once_with(501, modes.MODE_FILTER)

        getter = mock.AsyncMock(return_value="management")  # DB ko chhuna hi nahi chahiye
        with mock.patch.object(modes.db, "get_user_mode", new=getter):
            self.assertEqual(run(modes.get_user_mode(501)), modes.MODE_FILTER)
        getter.assert_not_awaited()

    def test_invalid_mode_not_saved(self):
        setter = mock.AsyncMock()
        with mock.patch.object(modes.db, "set_user_mode", new=setter):
            self.assertFalse(run(modes.set_user_mode(502, "nonsense")))
        setter.assert_not_awaited()

    def test_effective_mode_free_user_defaults_to_management(self):
        with mock.patch.object(modes.db, "get_user_mode", new=mock.AsyncMock(return_value=None)):
            self.assertEqual(
                run(modes.effective_user_mode(600, premium=False)), modes.MODE_MGMT)

    def test_effective_mode_premium_without_choice_is_none(self):
        """None = abhi choose nahi kiya → choice screen dikhega."""
        with mock.patch.object(modes.db, "get_user_mode", new=mock.AsyncMock(return_value=None)):
            self.assertIsNone(run(modes.effective_user_mode(600, premium=True)))

    def test_effective_mode_respects_saved_choice(self):
        with mock.patch.object(modes.db, "get_user_mode", new=mock.AsyncMock(return_value="filter")):
            self.assertEqual(
                run(modes.effective_user_mode(600, premium=True)), modes.MODE_FILTER)


class TestGroupMode(unittest.TestCase):
    """Group mode: naya add = MANAGEMENT, /add_group = FILTER."""

    def setUp(self):
        _reset_mode_cache()

    def test_unknown_group_defaults_to_management(self):
        """Group DB me hi nahi → bot abhi add hua → management."""
        with mock.patch.object(modes.db, "get_group_mode_info",
                               new=mock.AsyncMock(return_value=(False, None))):
            self.assertEqual(run(modes.get_group_mode(-1001)), modes.MODE_MGMT)
            self.assertTrue(run(modes.is_mgmt_group(-1001)))
            self.assertFalse(run(modes.is_filter_group(-1001)))

    def test_legacy_group_without_mode_stays_filter(self):
        """Purane auto-filter deployment ke groups ka behaviour na toote."""
        with mock.patch.object(modes.db, "get_group_mode_info",
                               new=mock.AsyncMock(return_value=(True, None))):
            self.assertEqual(run(modes.get_group_mode(-1002)), modes.MODE_FILTER)
            self.assertTrue(run(modes.is_filter_group(-1002)))

    def test_registered_group_is_filter(self):
        with mock.patch.object(modes.db, "get_group_mode_info",
                               new=mock.AsyncMock(return_value=(True, "filter"))):
            self.assertTrue(run(modes.is_filter_group(-1003)))
            self.assertFalse(run(modes.is_mgmt_group(-1003)))

    def test_set_group_mode_writes_and_caches(self):
        setter = mock.AsyncMock()
        with mock.patch.object(modes.db, "set_group_mode", new=setter):
            self.assertTrue(run(modes.set_group_mode(-1004, "filter")))
        setter.assert_awaited_once_with(-1004, modes.MODE_FILTER)

        getter = mock.AsyncMock(return_value=None)
        with mock.patch.object(modes.db, "get_group_mode_info", new=getter):
            self.assertEqual(run(modes.get_group_mode(-1004)), modes.MODE_FILTER)
        getter.assert_not_awaited()

    def test_db_failure_is_safe(self):
        with mock.patch.object(modes.db, "get_group_mode_info",
                               new=mock.AsyncMock(side_effect=RuntimeError("db down"))):
            self.assertEqual(run(modes.get_group_mode(-1005)), modes.MODE_MGMT)


class TestStartState(unittest.TestCase):
    """PM /start ka decision engine."""

    def setUp(self):
        _reset_mode_cache()
        import plugins.multibot as mb
        self.mb = mb

    def _state(self, stored, premium):
        with mock.patch.object(self.mb, "get_user_mode", new=mock.AsyncMock(return_value=stored)), \
             mock.patch.object(self.mb, "is_premium_capable", new=mock.AsyncMock(return_value=premium)):
            user = mock.MagicMock()
            user.id = 700
            return run(self.mb.resolve_start_state(user))

    def test_admin_or_premium_first_time_gets_choice(self):
        self.assertEqual(self._state(None, True), "pick")

    def test_free_user_gets_management(self):
        self.assertEqual(self._state(None, False), modes.MODE_MGMT)

    def test_saved_choice_is_respected(self):
        self.assertEqual(self._state("filter", True), modes.MODE_FILTER)
        self.assertEqual(self._state("management", False), modes.MODE_MGMT)
        # premium expire ho gaya par mode pehle chuna tha → wahi mode rehta hai
        self.assertEqual(self._state("filter", False), modes.MODE_FILTER)


class TestModeMenus(unittest.TestCase):
    """Choice screen + Management menu ke buttons."""

    def setUp(self):
        import plugins.multibot as mb
        self.mb = mb

    def test_picker_offers_both_modes(self):
        markup = self.mb.mode_picker_markup()
        datas = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn(f"mode_pick#{modes.MODE_FILTER}", datas)
        self.assertIn(f"mode_pick#{modes.MODE_MGMT}", datas)

    def _menu(self, mode, premium=False, admin=False):
        user = mock.MagicMock()
        user.id = 111 if admin else 900
        user.mention = "Tester"
        with mock.patch.object(self.mb, "is_premium_capable", new=mock.AsyncMock(return_value=premium)):
            return run(self.mb.build_mode_menu(user, mode))

    def test_management_menu_has_premium_button(self):
        text, markup = self._menu(modes.MODE_MGMT)
        labels = " ".join(b.text for row in markup.inline_keyboard for b in row)
        datas = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("Premium", labels)          # 💎 Join Premium
        self.assertIn("Group Manager Features", labels)
        self.assertIn("activate_plan", datas)
        # free user ko mode-switch ka button nahi milta (filter premium-only hai)
        self.assertNotIn("mode_open", datas)

    def test_premium_user_gets_switch_button(self):
        _, markup = self._menu(modes.MODE_MGMT, premium=True)
        datas = [b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn("mode_open", datas)

    def test_filter_menu_has_miniapp_and_switch(self):
        _, markup = self._menu(modes.MODE_FILTER, premium=True)
        datas = [b.callback_data for row in markup.inline_keyboard for b in row]
        labels = " ".join(b.text for row in markup.inline_keyboard for b in row)
        self.assertIn("Mini App", labels)
        self.assertIn("mode_open", datas)


class TestFreeUserModePick(unittest.TestCase):
    """Free user Auto Filter chunta hai → premium alert + GM menu (filter nahi)."""

    def test_free_user_cannot_pick_filter(self):
        import plugins.multibot as mb

        query = mock.MagicMock()
        query.data = f"mode_pick#{modes.MODE_FILTER}"
        query.from_user.id = 999
        query.from_user.mention = "Free User"
        query.answer = mock.AsyncMock()
        query.message.edit_caption = mock.AsyncMock()
        query.message.edit_text = mock.AsyncMock()

        setter = mock.AsyncMock()
        with mock.patch.object(mb, "is_premium_capable", new=mock.AsyncMock(return_value=False)), \
             mock.patch.object(mb, "set_user_mode", new=setter):
            run(mb.mode_pick_cb(mock.MagicMock(), query))

        setter.assert_not_awaited()                     # mode save nahi hota
        query.answer.assert_awaited()                   # premium alert
        self.assertTrue(query.answer.call_args[0][0].startswith("💎"))
        caption = query.message.edit_caption.call_args[1]["caption"]
        self.assertIn("Group Manager Bot", caption)

    def test_premium_user_pick_is_saved(self):
        import plugins.multibot as mb

        query = mock.MagicMock()
        query.data = f"mode_pick#{modes.MODE_FILTER}"
        query.from_user.id = 888
        query.from_user.mention = "Premium User"
        query.answer = mock.AsyncMock()
        query.message.edit_caption = mock.AsyncMock()

        setter = mock.AsyncMock(return_value=True)
        with mock.patch.object(mb, "is_premium_capable", new=mock.AsyncMock(return_value=True)), \
             mock.patch.object(mb, "set_user_mode", new=setter), \
             mock.patch.object(mb, "build_mode_menu",
                               new=mock.AsyncMock(return_value=("TXT", mock.MagicMock()))):
            run(mb.mode_pick_cb(mock.MagicMock(), query))

        setter.assert_awaited_once_with(888, modes.MODE_FILTER)
        query.message.edit_caption.assert_awaited()


class TestBlacklistMatchers(unittest.TestCase):
    """Pure matchers (words / links / media)."""

    def test_word_match_case_insensitive(self):
        from groupmgmt.blacklist import match_word
        self.assertEqual(match_word("Join My CHANNEL now", ["channel"]), "channel")
        self.assertIsNone(match_word("hello world", ["channel"]))
        self.assertIsNone(match_word("", ["channel"]))
        self.assertIsNone(match_word("anything", []))
        self.assertIsNone(match_word("anything", ["  "]))

    def test_extract_links(self):
        from groupmgmt.blacklist import extract_links
        found = extract_links("check https://Bad.com/x and www.spam.io plus t.me/xyz")
        self.assertIn("https://bad.com/x", found)
        self.assertIn("www.spam.io", found)
        self.assertIn("t.me/xyz", found)
        self.assertEqual(extract_links("no links here"), [])

    def test_link_blocked_and_whitelist_priority(self):
        from groupmgmt.blacklist import is_link_blocked
        self.assertTrue(is_link_blocked("https://spam.com/a", ["spam.com"], []))
        self.assertTrue(is_link_blocked("http://sub.spam.com", ["spam.com"], []))
        # whitelist hamesha jeetti hai
        self.assertFalse(is_link_blocked("https://spam.com/a", ["spam.com"], ["spam.com"]))
        self.assertFalse(is_link_blocked("https://ok.com", ["spam.com"], []))
        self.assertFalse(is_link_blocked("https://ok.com", [], []))

    def test_media_type_match(self):
        from groupmgmt.blacklist import match_media
        msg = mock.MagicMock(photo="x", video=None, document=None, sticker=None,
                             voice=None, animation=None, audio=None, video_note=None,
                             forward_date=None, forward_from=None, contact=None)
        self.assertEqual(match_media(msg, ["photo"]), "photo")
        self.assertIsNone(match_media(msg, ["video"]))
        self.assertIsNone(match_media(msg, []))

    def test_forward_detection(self):
        from groupmgmt.blacklist import detect_media_types
        msg = mock.MagicMock(photo=None, video=None, document=None, sticker=None,
                             voice=None, animation=None, audio=None, video_note=None,
                             contact=None, forward_date="2020-01-01", forward_from=None)
        self.assertIn("forward", detect_media_types(msg))


class TestLanguageFilter(unittest.TestCase):
    """Unicode-script based language detection."""

    def test_detect_common_languages(self):
        from groupmgmt.language import detect_language
        cases = {
            "यह एक हिंदी मैसेज है": "hi",
            "this is english text": "en",
            "مرحبا بالعالم": "ar",
            "नमस्ते hello": "hi",          # mixed me dominant script jeetta hai
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(detect_language(text), expected)

    def test_emoji_only_is_unknown(self):
        from groupmgmt.language import detect_language
        self.assertEqual(detect_language("🎉🎉🎉"), "unknown")
        self.assertEqual(detect_language("12345 !!!"), "unknown")
        self.assertEqual(detect_language(""), "unknown")
        self.assertEqual(detect_language(None), "unknown")

    def test_normalize_codes(self):
        from groupmgmt.language import normalize_lang_codes
        self.assertEqual(normalize_lang_codes("hindi, English"), ["hi", "en"])
        self.assertEqual(normalize_lang_codes(["HI", "hi", "hindi"]), ["hi"])
        self.assertEqual(normalize_lang_codes("klingon"), [])
        self.assertEqual(normalize_lang_codes(None), [])

    def test_check_language_off_when_empty(self):
        from groupmgmt.language import check_language
        blocked, _ = run(check_language("यह हिंदी है", {"allowed_langs": []}))
        self.assertFalse(blocked)

    def test_check_language_blocks_disallowed(self):
        from groupmgmt.language import check_language
        settings = {"allowed_langs": ["en"]}
        blocked, lang = run(check_language("यह हिंदी है", settings))
        self.assertTrue(blocked)
        self.assertEqual(lang, "hi")

        blocked, lang = run(check_language("this is fine", settings))
        self.assertFalse(blocked)
        self.assertEqual(lang, "en")

    def test_unknown_language_never_blocked(self):
        from groupmgmt.language import check_language
        blocked, _ = run(check_language("🎉🎉", {"allowed_langs": ["en"]}))
        self.assertFalse(blocked)

    def test_no_settings_no_chat_id_is_off(self):
        from groupmgmt.language import check_language
        self.assertFalse(run(check_language("यह हिंदी है"))[0])


class TestViolationFlow(unittest.TestCase):
    """handle_violation: delete → warn → auto-ban."""

    def _run(self, warns_before, limit=3, is_admin=False, delete_on=True):
        from groupmgmt import core

        client = mock.MagicMock()
        client.delete_messages = mock.AsyncMock()
        client.send_message = mock.AsyncMock()
        client.ban_chat_member = mock.AsyncMock()

        message = mock.MagicMock()
        message.chat.id = -100
        message.id = 5
        message.text = "spam"
        message.from_user.id = 999
        message.from_user.first_name = "Spammer"
        message.from_user.is_bot = False

        settings = {"warn_limit": limit, "delete_on_violation": delete_on}

        with mock.patch.object(core, "get_gm_settings", new=mock.AsyncMock(return_value=settings)), \
             mock.patch.object(core, "get_warn_count", new=mock.AsyncMock(return_value=warns_before)), \
             mock.patch.object(core.db, "set_warn", new=mock.AsyncMock()), \
             mock.patch.object(core, "reset_warn", new=mock.AsyncMock()), \
             mock.patch.object(core, "is_check_admin", new=mock.AsyncMock(return_value=is_admin)), \
             mock.patch.object(core, "ban_member", new=mock.AsyncMock(return_value=True)) as ban_mock:
            result = run(core.handle_violation(
                client, message, "Blacklisted word", settings=settings))

        return result, client, ban_mock

    def test_deletes_and_warns(self):
        result, client, ban = self._run(warns_before=0)
        client.delete_messages.assert_awaited()
        client.send_message.assert_awaited()
        ban.assert_not_awaited()
        self.assertEqual(result["count"], 1)
        self.assertFalse(result["banned"])

    def test_auto_ban_on_limit(self):
        result, _, ban = self._run(warns_before=2, limit=3)
        ban.assert_awaited()
        self.assertTrue(result["banned"])

    def test_no_delete_when_disabled(self):
        _, client, _ = self._run(warns_before=0, delete_on=False)
        client.delete_messages.assert_not_awaited()

    def test_group_admin_never_touched(self):
        result, client, _ = self._run(warns_before=0, is_admin=True)
        client.delete_messages.assert_not_awaited()
        self.assertEqual(result["count"], 0)


class TestGroupSearchModeGate(unittest.TestCase):
    """🔒 FILTER-group me auto-filter, MGMT-group me sirf management."""

    def _group_search(self, mgmt):
        import plugins.filter as flt

        message = mock.MagicMock()
        message.chat.id = -100
        message.chat.type = enums.ChatType.SUPERGROUP
        message.text = "avengers"
        message.forward_date = None
        message.photo = None
        message.video = None
        message.document = None
        message.entities = None
        message.from_user.id = 999

        auto = mock.AsyncMock()
        with mock.patch.object(flt, "is_mgmt_chat", new=mock.AsyncMock(return_value=mgmt)), \
             mock.patch.object(flt, "auto_filter", new=auto), \
             mock.patch.object(flt, "get_settings", new=mock.AsyncMock(return_value={"search_enabled": True})):
            run(flt.group_search(mock.MagicMock(), message))
        return auto

    def test_mgmt_group_skips_auto_filter(self):
        self._group_search(mgmt=True).assert_not_awaited()

    def test_filter_group_runs_auto_filter_gate(self):
        """Non-premium user par auto_filter nahi (premium gate), par code path chalta hai."""
        import plugins.filter as flt
        with mock.patch.object(flt, "is_mgmt_chat", new=mock.AsyncMock(return_value=False)), \
             mock.patch.object(flt, "is_premium", new=mock.AsyncMock(return_value=False)), \
             mock.patch.object(flt, "auto_filter", new=mock.AsyncMock()) as auto, \
             mock.patch.object(flt, "get_settings", new=mock.AsyncMock(return_value={"search_enabled": True})):
            message = mock.MagicMock()
            message.chat.id = -100
            message.text = "avengers"
            message.forward_date = None
            message.photo = None
            message.video = None
            message.document = None
            message.entities = None
            message.from_user.id = 999
            run(flt.group_search(mock.MagicMock(), message))
        auto.assert_not_awaited()


class TestBlacklistEnforcerGate(unittest.TestCase):
    """Blacklist enforcement sirf MGMT group me."""

    def _enforce(self, enabled):
        import groupmgmt.blacklist as bl

        message = mock.MagicMock()
        message.chat.id = -100
        message.text = "badword here"
        message.caption = None
        message.from_user.id = 999
        message.from_user.is_bot = False

        violate = mock.AsyncMock()
        with mock.patch.object(bl, "gm_enabled", new=mock.AsyncMock(return_value=enabled)), \
             mock.patch.object(bl, "handle_violation", new=violate), \
             mock.patch.object(bl, "get_gm_settings",
                               new=mock.AsyncMock(return_value={"blacklist": ["badword"]})):
            run(bl.blacklist_enforcer(mock.MagicMock(), message))
        return violate

    def test_blocks_when_management_mode(self):
        self._enforce(True).assert_awaited()

    def test_silent_when_filter_mode(self):
        self._enforce(False).assert_not_awaited()


class TestBotAddedToGroupSetsMgmtMode(unittest.TestCase):
    """⭐ User ka main rule: group me bot ADD hua → MANAGEMENT mode."""

    def test_welcome_handler_sets_management_mode(self):
        import plugins.p_ttishow as pt
        from hydrogram import enums

        update = mock.MagicMock()
        update.chat.id = -100999
        update.chat.title = "Test Group"
        update.chat.username = "testgrp"
        update.chat.type = enums.ChatType.SUPERGROUP
        update.from_user.mention = "Adder"
        update.new_chat_member.user.id = 424242
        update.old_chat_member = None

        client = mock.MagicMock()
        client.send_photo = mock.AsyncMock()
        client.send_message = mock.AsyncMock()
        client.get_chat_members_count = mock.AsyncMock(return_value=10)

        set_mode = mock.AsyncMock(return_value=modes.MODE_MGMT)

        with mock.patch.object(pt.temp, "ME", 424242), \
             mock.patch.object(pt.db, "add_chat", new=mock.AsyncMock()), \
             mock.patch.object(pt.db, "get_chat", new=mock.AsyncMock(return_value=None)), \
             mock.patch.object(pt, "ensure_mode_after_bot_add", new=set_mode):
            run(pt.welcome(client, update))

        set_mode.assert_awaited_once_with(-100999)
        client.send_photo.assert_awaited()
        # mode MANAGEMENT hai to welcome text bhi wahi bolna chahiye
        self.assertIn("Group Manager Bot", client.send_photo.call_args[0][2])



class TestBotReAddedToFilterGroup(unittest.TestCase):
    """Registered auto-filter group me dobara add hone par welcome bhi filter."""

    def test_welcome_text_matches_filter_mode(self):
        import plugins.p_ttishow as pt

        update = mock.MagicMock()
        update.chat.id = -100888
        update.chat.title = "Filter Group"
        update.chat.username = "fgrp"
        update.chat.type = enums.ChatType.SUPERGROUP
        update.from_user.mention = "Adder"
        update.new_chat_member.user.id = 424242
        update.old_chat_member = None

        client = mock.MagicMock()
        client.send_photo = mock.AsyncMock()
        client.send_message = mock.AsyncMock()
        client.get_chat_members_count = mock.AsyncMock(return_value=10)

        with mock.patch.object(pt.temp, "ME", 424242), \
             mock.patch.object(pt.db, "add_chat", new=mock.AsyncMock()), \
             mock.patch.object(pt.db, "get_chat", new=mock.AsyncMock(return_value={"is_disabled": False})), \
             mock.patch.object(pt, "ensure_mode_after_bot_add",
                               new=mock.AsyncMock(return_value=modes.MODE_FILTER)):
            run(pt.welcome(client, update))

        text = client.send_photo.call_args[0][2]
        self.assertIn("Auto Filter Bot", text)
        # purane group ke liye dobara #NewGroup alert nahi
        client.send_message.assert_not_awaited()


class TestModeAfterBotAdd(unittest.TestCase):
    """modes.ensure_mode_after_bot_add — naya add vs registered group."""

    def setUp(self):
        _reset_mode_cache()

    def _call(self, registered, raw):
        setter = mock.AsyncMock(return_value=True)
        with mock.patch.object(modes.db, "get_group_mode_info",
                               new=mock.AsyncMock(return_value=(registered, raw))), \
             mock.patch.object(modes, "set_group_mode", new=setter):
            result = run(modes.ensure_mode_after_bot_add(-100200))
        return result, setter

    def test_fresh_group_becomes_management(self):
        result, setter = self._call(False, None)
        self.assertEqual(result, modes.MODE_MGMT)
        setter.assert_awaited_once_with(-100200, modes.MODE_MGMT)

    def test_legacy_group_without_mode_becomes_management_on_readd(self):
        result, setter = self._call(True, None)
        self.assertEqual(result, modes.MODE_MGMT)
        setter.assert_awaited_once()

    def test_registered_filter_group_is_not_overridden(self):
        """Admin ne /add_group kiya tha — dobara add karne par FILTER hi rahe."""
        result, setter = self._call(True, "filter")
        self.assertEqual(result, modes.MODE_FILTER)
        setter.assert_not_awaited()

    def test_db_error_still_sets_management(self):
        setter = mock.AsyncMock(return_value=True)
        with mock.patch.object(modes.db, "get_group_mode_info",
                               new=mock.AsyncMock(side_effect=RuntimeError("db down"))), \
             mock.patch.object(modes, "set_group_mode", new=setter):
            result = run(modes.ensure_mode_after_bot_add(-100201))
        self.assertEqual(result, modes.MODE_MGMT)
        setter.assert_awaited_once()


class TestGroupRegistryCommands(unittest.TestCase):
    """Bot-admin ke /add_group → FILTER, /rm_group → MANAGEMENT."""

    def _cmd(self, func, args):
        import plugins.multibot as mb

        message = mock.MagicMock()
        message.command = args
        message.text = " ".join(args)
        message.reply = mock.AsyncMock()

        client = mock.MagicMock()
        client.get_chat = mock.AsyncMock(side_effect=Exception("not a member"))
        client.send_message = mock.AsyncMock()

        set_mode = mock.AsyncMock(return_value=True)
        with mock.patch.object(mb, "set_group_mode", new=set_mode), \
             mock.patch.object(mb.db, "add_chat", new=mock.AsyncMock()):
            run(func(client, message))
        return set_mode, message

    def test_add_group_registers_filter_mode(self):
        import plugins.multibot as mb
        set_mode, message = self._cmd(mb.add_group_cmd, ["/add_group", "-100777"])
        set_mode.assert_awaited_once_with(-100777, modes.MODE_FILTER)

    def test_rm_group_switches_back_to_management(self):
        import plugins.multibot as mb
        set_mode, _ = self._cmd(mb.rm_group_cmd, ["/rm_group", "-100777"])
        set_mode.assert_awaited_once_with(-100777, modes.MODE_MGMT)

    def test_set_gmode_explicit(self):
        import plugins.multibot as mb
        set_mode, _ = self._cmd(mb.set_gmode_cmd, ["/set_gmode", "-100778", "filter"])
        set_mode.assert_awaited_once_with(-100778, modes.MODE_FILTER)

    def test_bad_id_is_rejected(self):
        import plugins.multibot as mb
        set_mode, message = self._cmd(mb.add_group_cmd, ["/add_group", "not-an-id"])
        set_mode.assert_not_awaited()
        self.assertTrue(message.reply.called)


class TestGroupStartReply(unittest.TestCase):
    """Group me /start par mode ke hisaab se reply."""

    def _start(self, mode):
        import plugins.commands as cmds

        message = mock.MagicMock()
        message.chat.id = -100555
        message.chat.type = enums.ChatType.SUPERGROUP
        message.chat.title = "Mode Test Group"
        message.chat.username = "modegroup"
        message.text = "/start"
        message.command = ["start"]
        message.from_user.mention = "User"
        message.reply = mock.AsyncMock()

        client = mock.MagicMock()
        client.get_chat_members_count = mock.AsyncMock(return_value=5)
        client.send_message = mock.AsyncMock()

        with mock.patch.object(cmds, "get_group_mode", new=mock.AsyncMock(return_value=mode)), \
             mock.patch.object(cmds.db, "get_chat",
                               new=mock.AsyncMock(return_value={"is_disabled": False})):
            run(cmds.start(client, message))
        return message.reply.call_args

    def test_mgmt_group_gets_manager_reply(self):
        args = self._start(modes.MODE_MGMT)
        text = args[0][0]
        self.assertIn("Group Manager Bot", text)

    def test_filter_group_gets_classic_reply(self):
        args = self._start(modes.MODE_FILTER)
        text = args[0][0]
        self.assertIn("How can I help you", text)


class TestFilterOnlyCommandsHint(unittest.TestCase):
    """/search aur /settings MGMT group me filter ke bajaye manager panel."""

    def test_search_command_explains_mode(self):
        import plugins.filter as flt

        message = mock.MagicMock()
        message.chat.id = -100666
        message.chat.type = enums.ChatType.SUPERGROUP
        message.command = ["search", "off"]
        message.from_user.id = 111
        message.reply = mock.AsyncMock()

        save = mock.AsyncMock()
        with mock.patch.object(flt, "is_check_admin", new=mock.AsyncMock(return_value=True)), \
             mock.patch.object(flt, "is_mgmt_chat", new=mock.AsyncMock(return_value=True)), \
             mock.patch.object(flt, "save_group_settings", new=save):
            run(flt.search_toggle(mock.MagicMock(), message))

        save.assert_not_awaited()
        self.assertIn("Group Manager mode", message.reply.call_args[0][0])

    def test_settings_command_shows_manager_panel(self):
        import plugins.filter as flt

        message = mock.MagicMock()
        message.chat.id = -100667
        message.chat.type = enums.ChatType.SUPERGROUP
        message.chat.title = "Panel Group"
        message.from_user.id = 111
        message.reply = mock.AsyncMock()

        with mock.patch.object(flt, "is_check_admin", new=mock.AsyncMock(return_value=True)), \
             mock.patch.object(flt, "is_mgmt_chat", new=mock.AsyncMock(return_value=True)), \
             mock.patch.object(flt, "get_settings",
                               new=mock.AsyncMock(return_value={"mgmt_enabled": True,
                                                                "delete_on_violation": True,
                                                                "warn_limit": 3})):
            run(flt.group_settings_panel(mock.MagicMock(), message))

        text = message.reply.call_args[0][0]
        self.assertIn("Group Manager Control Panel", text)


class TestExtraPluginRootLoading(unittest.TestCase):
    """bot.py ka multi-root plugin loader."""

    def test_groupmgmt_is_an_extra_root(self):
        from bot import EXTRA_PLUGIN_ROOTS
        self.assertIn("groupmgmt", EXTRA_PLUGIN_ROOTS)

    def test_loader_registers_groupmgmt_handlers(self):
        """Loader ko groupmgmt root se actually handlers milne chahiye."""
        from bot import Bot

        class FakeApp:
            name = "FakeApp"

            def __init__(self):
                self.added = []

            def add_handler(self, handler, group):
                self.added.append((handler, group))

        fake = FakeApp()
        Bot._load_plugin_root(fake, "groupmgmt")
        self.assertGreater(len(fake.added), 15,
                           "groupmgmt root se koi handler register nahi hua")
        # saare handlers group 0 (default) me hone chahiye
        self.assertTrue(all(g == 0 for _h, g in fake.added))

    def test_groupmgmt_handlers_are_real(self):
        """groupmgmt package me actually handlers hain (loader ko kuch mile)."""
        import importlib
        import pkgutil
        import groupmgmt

        found = 0
        for mod in pkgutil.iter_modules(groupmgmt.__path__):
            if mod.name == "core":
                continue
            module = importlib.import_module("groupmgmt." + mod.name)
            for obj in vars(module).values():
                found += len(getattr(obj, "handlers", []) or [])
        self.assertGreater(found, 15)


class TestAntiflood(unittest.TestCase):
    """Antiflood: window ke andar limit cross hone par flood."""

    def setUp(self):
        from groupmgmt import antiflood
        self.af = antiflood
        self.af._FLOOD.clear()

    def test_off_when_limit_zero(self):
        is_flood, count = self.af.record_message(-1, 5, limit=0, window=10)
        self.assertFalse(is_flood)
        self.assertEqual(count, 0)

    def test_floods_on_limit(self):
        results = [self.af.record_message(-1, 5, limit=3, window=10, now=100.0 + i * 0.1)[0]
                   for i in range(3)]
        self.assertEqual(results, [False, False, True])

    def test_old_messages_expire(self):
        self.af.record_message(-1, 5, limit=2, window=5, now=100.0)
        # window ke baad wala message flood nahi maana jayega
        self.assertFalse(self.af.record_message(-1, 5, limit=2, window=5, now=200.0)[0])

    def test_per_user_and_per_chat_isolation(self):
        self.af.record_message(-1, 5, limit=2, window=10, now=100.0)
        self.assertFalse(self.af.record_message(-1, 6, limit=2, window=10, now=100.1)[0])
        self.assertFalse(self.af.record_message(-2, 5, limit=2, window=10, now=100.2)[0])

    def test_reset_clears_bucket(self):
        self.af.record_message(-1, 5, limit=2, window=10, now=100.0)
        self.af.reset_user(-1, 5)
        self.assertFalse(self.af.record_message(-1, 5, limit=2, window=10, now=100.5)[0])

    def test_config_parsing(self):
        self.assertEqual(self.af.flood_config({}), (0, self.af.DEFAULT_WINDOW))
        self.assertEqual(self.af.flood_config({"antiflood": {"limit": 4, "window": 8}}), (4, 8))
        self.assertEqual(self.af.flood_config({"antiflood": "junk"}), (0, self.af.DEFAULT_WINDOW))
        # window missing → default
        self.assertEqual(self.af.flood_config({"antiflood": {"limit": 3}}), (3, self.af.DEFAULT_WINDOW))

    def test_bucket_cache_is_bounded(self):
        self.assertLessEqual(self.af._FLOOD.get_size(), 2000)


class TestGroupManagerFeaturesCoverage(unittest.TestCase):
    """User ne maange gaye saare group-manager features registered hone chahiye."""

    EXPECTED_COMMANDS = {
        # blacklist
        "addword", "rmword", "words",
        "addlink", "rmlink", "links", "allowlink", "rmallow",
        "blockmedia", "unblockmedia",
        # language
        "setlang", "offlang", "langs",
        # moderation
        "warn", "warnings", "resetwarn", "setwarnlimit",
        "ban", "unban", "mute", "unmute", "kick", "purge",
        "lock", "unlock", "slowmode", "banlist", "antiflood",
        # reports
        "report",
        # panel
        "gm",
        # multi-bot registry
        "add_group", "rm_group", "set_gmode", "list_groups", "mode",
    }

    def test_all_expected_commands_registered(self):
        from tests.test_core import _live_bot_commands
        live = _live_bot_commands()
        missing = sorted(self.EXPECTED_COMMANDS - live)
        self.assertEqual(missing, [], "Ye group-manager commands live nahi hain: "
                                       + ", ".join("/" + c for c in missing))

    def test_blacklist_settings_defaults_exist(self):
        from database.users_chats_db import db
        for key in ("blacklist", "block_links", "allow_links", "block_media",
                    "allowed_langs", "warn_limit", "delete_on_violation",
                    "banned_users", "muted_users", "mgmt_enabled", "antiflood"):
            with self.subTest(key=key):
                self.assertIn(key, db.df_set)


if __name__ == "__main__":
    unittest.main(verbosity=2)
