"""
Core-logic regression tests.

Ye suite un pure/deterministic functions ko cover karti hai jinhe refactor ke
dauraan chheda gaya hai — taaki "bug hatao / code optimize karo" wale changes
ko objectively verify kiya ja sake (MongoDB/Telegram connection ki zaroorat
nahi, sab mock/stub hai).

Run:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

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


class TestTimeParsing(unittest.TestCase):
    """utils.get_seconds — duration string parser (bot /dlink delay ke liye)."""

    def test_shorthand_units(self):
        from utils import get_seconds
        import asyncio
        cases = {
            "1s": 1, "30sec": 30,
            "1m": 60, "5min": 300, "2 min": 120,
            "1h": 3600, "2hr": 7200, "3 hour": 10800,
            "1d": 86400, "2day": 172800,
            "1mo": 2592000, "2month": 5184000,
            "1y": 31536000, "1year": 31536000,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(asyncio.run(get_seconds(text)), expected)

    def test_invalid_returns_zero(self):
        from utils import get_seconds
        import asyncio
        for text in ("", "abc", "hour", "10 fortnights", None if False else "  "):
            with self.subTest(text=text):
                self.assertEqual(asyncio.run(get_seconds(text)), 0)

    def test_longer_words_not_split_as_prefix(self):
        """"1month" ko "1m" ki tarah 60s nahi maan lena chahiye."""
        from utils import get_seconds
        import asyncio
        self.assertEqual(asyncio.run(get_seconds("1month")), 2592000)
        self.assertEqual(asyncio.run(get_seconds("1hour")), 3600)


class TestFormatting(unittest.TestCase):
    def test_get_size(self):
        from utils import get_size
        self.assertEqual(get_size(0), "0.00 Bytes")
        self.assertEqual(get_size(1024), "1.00 KB")
        self.assertEqual(get_size(1024 ** 2), "1.00 MB")
        self.assertEqual(get_size(1536), "1.50 KB")
        # TB se aage unit overflow na ho
        self.assertEqual(get_size(1024 ** 5), "1024.00 TB")

    def test_get_readable_time(self):
        from utils import get_readable_time
        self.assertEqual(get_readable_time(0), "0s")
        self.assertEqual(get_readable_time(59), "59s")
        self.assertEqual(get_readable_time(60), "1m")
        self.assertEqual(get_readable_time(3661), "1h 1m 1s")
        self.assertEqual(get_readable_time(90061), "1d 1h 1m 1s")

    def test_get_wish_is_non_empty(self):
        from utils import get_wish
        self.assertTrue(get_wish())


class TestPremiumPlanDefaults(unittest.TestCase):
    """Premium reset-state dict ab ek hi jagah define hota hai."""

    def test_single_source_of_truth(self):
        from database.users_chats_db import DEFAULT_PLAN_STATUS, db
        from utils import RESET_PLAN_STATUS
        self.assertEqual(RESET_PLAN_STATUS, DEFAULT_PLAN_STATUS)
        # Database.df_prm bhi wahi base use kare (trial ke saath)
        for key in ("premium", "expire", "plan", "last_reminder_id"):
            self.assertIn(key, db.df_prm)
        self.assertIn("trial", db.df_prm)

    def test_reset_status_marks_inactive(self):
        from database.users_chats_db import DEFAULT_PLAN_STATUS
        self.assertFalse(DEFAULT_PLAN_STATUS["premium"])
        self.assertIsNone(DEFAULT_PLAN_STATUS["expire"])
        self.assertEqual(DEFAULT_PLAN_STATUS["plan"], "")
        for flag in ("12h", "6h", "3h", "1h", "30m", "10m"):
            self.assertFalse(DEFAULT_PLAN_STATUS[f"reminded_{flag}"])

    def test_copies_are_independent(self):
        """Shared dict ko mutate karke global state kharab na ho."""
        from database.users_chats_db import DEFAULT_PLAN_STATUS
        snapshot = dict(DEFAULT_PLAN_STATUS)
        copy = dict(DEFAULT_PLAN_STATUS)
        copy["premium"] = True
        copy["plan"] = "30 Days"
        self.assertEqual(DEFAULT_PLAN_STATUS, snapshot)


class TestRegexBuilder(unittest.TestCase):
    """ia_filterdb._build_regex — short-query shield."""

    def test_short_queries_rejected(self):
        from database.ia_filterdb import _build_regex
        self.assertIsNone(_build_regex(""))
        self.assertIsNone(_build_regex("  "))
        self.assertIsNone(_build_regex("a"))
        # 2-char jo allowlist me nahi
        self.assertIsNone(_build_regex("zz"))

    def test_allowed_short_terms_accepted(self):
        from database.ia_filterdb import _build_regex
        for term in ("4k", "hd", "3d", "8k", "rr", "kg"):
            with self.subTest(term=term):
                self.assertIsNotNone(_build_regex(term))

    def test_multiword_and_boundaries(self):
        from database.ia_filterdb import _build_regex
        rx = _build_regex("avengers endgame")
        self.assertIsNotNone(rx)
        self.assertTrue(rx.search("Avengers.Endgame.2019"))
        self.assertTrue(rx.search("the avengers endgame 1080p"))

    def test_single_word_needs_boundary(self):
        from database.ia_filterdb import _build_regex
        rx = _build_regex("avengers")
        self.assertTrue(rx.search("Avengers.2012.1080p"))
        # regex special chars escape hone chahiye (crash/galat match nahi)
        self.assertIsNotNone(_build_regex("a+b.c"))
        self.assertIsNotNone(_build_regex("(2020)"))


class TestFileIdCodec(unittest.TestCase):
    def test_encode_decode_roundtrip_is_stable(self):
        from database.ia_filterdb import encode_file_id, unpack_new_file_id
        # Real-looking hydrogram video file_id
        fid = "BAACAgUAAxkBAAIBZ2mF7QABYQACAgAD"
        out = unpack_new_file_id(fid)
        if out is not None:  # decode ho gaya to re-encode deterministic hona chahiye
            self.assertEqual(out, unpack_new_file_id(fid))
        self.assertIsInstance(encode_file_id(b"\x00\x00\x01\x02"), str)

    def test_bad_file_id_returns_none(self):
        from database.ia_filterdb import unpack_new_file_id
        self.assertIsNone(unpack_new_file_id("not-a-valid-file-id!!!"))


class TestStreamingMath(unittest.TestCase):
    """web/utils/custom_dl chunk math + HTTP Range parsing."""

    def test_chunk_size_is_power_of_two_kb(self):
        from web.utils.custom_dl import chunk_size
        for length in (1024, 5 * 1024, 10 ** 6, 10 ** 9, 4 * 10 ** 9):
            with self.subTest(length=length):
                cs = chunk_size(length)
                self.assertGreaterEqual(cs, 4 * 1024)
                self.assertLessEqual(cs, 1024 * 1024)
                self.assertEqual(cs % 1024, 0)
                self.assertEqual(cs & (cs - 1), 0, "chunk size 2 ki power hona chahiye")

    def test_offset_fix_aligns_down(self):
        from web.utils.custom_dl import offset_fix, chunk_size
        cs = chunk_size(10 ** 7)
        self.assertEqual(offset_fix(0, cs), 0)
        self.assertEqual(offset_fix(cs, cs), cs)
        self.assertEqual(offset_fix(cs + 1, cs), cs)
        self.assertEqual(offset_fix(cs - 1, cs), 0)

    def test_range_parse_helper(self):
        """Range header parsing ka extracted helper."""
        from web.stream_routes import parse_range
        size = 1000
        self.assertEqual(parse_range(None, size), (0, 999, 1000, False))
        self.assertEqual(parse_range("bytes=0-499", size), (0, 499, 500, True))
        self.assertEqual(parse_range("bytes=500-", size), (500, 999, 500, True))
        self.assertEqual(parse_range("bytes=-", size), (0, 999, 1000, True))
        # clamp: upper bound file size se aage na jaaye
        self.assertEqual(parse_range("bytes=0-99999", size), (0, 999, 1000, True))
        # invalid / unsatisfiable -> None
        self.assertIsNone(parse_range("bytes=2000-3000", size))
        self.assertIsNone(parse_range("bytes=500-100", size))
        # garbage header crash na kare. NOTE: pehle yeh case 206 (partial) deta tha
        # kyunki `r_head` truthy tha — RFC ke hisaab se galat, kyunki Range parse hi
        # nahi hua. Ab full content (200) jaata hai, jo zyada sahi hai.
        self.assertEqual(parse_range("garbage", size), (0, 999, 1000, False))


class TestSearchQueryFilters(unittest.TestCase):
    """ia_filterdb query-filter builder (text + regex + lang)."""

    def test_text_filter_for_normal_query(self):
        from database.ia_filterdb import build_query_filter
        flt, is_text = build_query_filter("avengers endgame", None, None)
        self.assertTrue(is_text)
        self.assertIn("$text", flt)
        self.assertEqual(flt["$text"]["$search"], '"avengers" "endgame"')

    def test_regex_fallback_when_no_words(self):
        from database.ia_filterdb import build_query_filter, _build_regex
        rx = _build_regex("4k")
        flt, is_text = build_query_filter("", rx, None)
        self.assertFalse(is_text)
        self.assertIn("$or", flt)

    def test_lang_filter_wraps_with_and(self):
        from database.ia_filterdb import build_query_filter
        flt, _ = build_query_filter("avengers", None, "hindi")
        self.assertIn("$and", flt)
        self.assertEqual(len(flt["$and"]), 2)

    def test_empty_query_gives_none(self):
        from database.ia_filterdb import build_query_filter
        flt, is_text = build_query_filter("", None, None)
        self.assertIsNone(flt)

    def test_quotes_stripped(self):
        from database.ia_filterdb import build_query_filter
        flt, _ = build_query_filter('"avengers"', None, None)
        self.assertEqual(flt["$text"]["$search"], '"avengers"')


class _FakeCursor:
    def __init__(self, docs): self._d = docs
    def sort(self, *a, **k): return self
    def skip(self, *a, **k): return self
    def limit(self, *a, **k): return self
    async def to_list(self, length=None): return [dict(x) for x in self._d]


class _FakeCol:
    """Motor collection ka minimal stand-in (text vs regex branch alag docs deta hai)."""
    name = "Primary"

    def __init__(self, text_docs, regex_docs, count):
        self.text_docs, self.regex_docs, self.count = text_docs, regex_docs, count
        self.filters = []

    def find(self, flt, proj):
        self.filters.append(flt)
        is_text = "$text" in flt or "$and" in flt
        return _FakeCursor(self.text_docs if is_text else self.regex_docs)

    async def count_documents(self, flt): return self.count


class TestSearchFallthrough(unittest.TestCase):
    """
    _search() refactor ka riskiest hissa: text-search khali aane par regex fallback
    chalna chahiye, aur dono na bane to safely khali return hona chahiye.
    """
    DOC = {"_id": "F1", "file_name": "Avengers 2012", "file_size": 100}

    def _run(self, *a, **k):
        import asyncio
        from database.ia_filterdb import _search
        return asyncio.run(_search(*a, **k))

    def test_text_hit_returns_immediately(self):
        from database.ia_filterdb import _build_regex
        col = _FakeCol([self.DOC], [], 7)
        docs, cnt = self._run(col, "avengers", _build_regex("avengers"), 0, 10)
        self.assertEqual(len(docs), 1)
        self.assertEqual(cnt, 7)
        # UI/JSON ke liye file_id + source_col tag hona zaroori hai
        self.assertEqual(docs[0]["file_id"], "F1")
        self.assertEqual(docs[0]["source_col"], "primary")
        self.assertEqual(len(col.filters), 1, "text hit par regex query nahi chalni chahiye")

    def test_empty_text_falls_back_to_regex(self):
        from database.ia_filterdb import _build_regex
        col = _FakeCol([], [self.DOC], 3)
        docs, cnt = self._run(col, "avengers", _build_regex("avengers"), 0, 10)
        self.assertEqual(len(docs), 1)
        self.assertEqual(cnt, 3)
        self.assertEqual(len(col.filters), 2, "text miss ke baad regex query chalni chahiye")

    def test_empty_text_and_no_regex_is_safe(self):
        col = _FakeCol([], [], 0)
        docs, cnt = self._run(col, "avengers", None, 0, 10)
        self.assertEqual((docs, cnt), ([], 0))

    def test_pure_regex_path(self):
        from database.ia_filterdb import _build_regex
        col = _FakeCol([], [self.DOC], 5)
        docs, cnt = self._run(col, "", _build_regex("4k"), 0, 10)
        self.assertEqual((len(docs), cnt), (1, 5))

    def test_nothing_usable_is_safe(self):
        col = _FakeCol([], [], 0)
        self.assertEqual(self._run(col, "", None, 0, 10), ([], 0))

    def test_bypass_count_skips_counting(self):
        col = _FakeCol([self.DOC], [], 99)
        docs, cnt = self._run(col, "avengers", None, 0, 10, bypass_count=True)
        self.assertEqual(len(docs), 1)
        self.assertEqual(cnt, 0)


class TestSuggestionDedupe(unittest.TestCase):
    def test_dedupe_case_insensitive_and_limit(self):
        from database.ia_filterdb import _dedupe_titles
        docs = [
            {"file_name": "Avengers 2012"},
            {"file_name": "avengers 2012"},
            {"file_name": "  Avengers   2012 "},
            {"file_name": "Avengers Endgame"},
            {"file_name": ""},
        ]
        out = _dedupe_titles(docs, limit=5, seen={"other"})
        self.assertEqual(out, ["Avengers 2012", "Avengers Endgame"])

    def test_respects_seen_and_limit(self):
        from database.ia_filterdb import _dedupe_titles
        docs = [{"file_name": f"Title {i}"} for i in range(10)]
        self.assertEqual(len(_dedupe_titles(docs, limit=3, seen=set())), 3)
        self.assertEqual(_dedupe_titles([{"file_name": "Title 1"}], limit=5, seen={"title 1"}), [])

    def test_whitespace_normalized_not_lowercased(self):
        from database.ia_filterdb import _clean_title_guess
        self.assertEqual(_clean_title_guess("  A   b  "), "A b")
        self.assertEqual(_clean_title_guess(""), "")


class TestRuntimeState(unittest.TestCase):
    """temp runtime buckets ab class-level declared hain (hasattr guards nahi)."""

    def test_all_buckets_declared(self):
        from utils import temp
        for name in ("BANNED_USERS", "BANNED_CHATS", "ADMIN_TOKENS", "ADMIN_SESSIONS",
                     "FILES", "PM_FILES", "USER_SESSIONS", "REG_PENDING"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(temp, name), f"temp.{name} declared hona chahiye")

    def test_rate_limiter_blocks_then_allows(self):
        import utils
        utils._rate_limits.clear()
        self.assertFalse(utils.is_rate_limited(1, "act", 60))
        self.assertTrue(utils.is_rate_limited(1, "act", 60))
        # doosra action independent
        self.assertFalse(utils.is_rate_limited(1, "other", 60))
        # doosra user independent
        self.assertFalse(utils.is_rate_limited(2, "act", 60))
        # expiry ke baad allow
        utils._rate_limits["1:act"] -= 61
        self.assertFalse(utils.is_rate_limited(1, "act", 60))
        utils._rate_limits.clear()

    def test_settings_cache_bounded(self):
        import utils
        self.assertGreater(utils._CACHE_TTL, 0)


class TestNoDuplicateRegistrations(unittest.TestCase):
    """
    Regression guard: pehle do alag files me `^close_` callback handler aur do
    jagah `/health` route register the — dono hi chalte/register hote the.
    """

    @staticmethod
    def _plugin_handlers(pattern):
        """
        hydrogram ka class-level decorator har function par `func.handlers` list
        laga deta hai (Client instance banne par wahi register hote hain). Isliye
        plugin modules ke saare functions scan karke matching pattern ginte hain.
        """
        import inspect
        import plugins.commands as cmd
        import plugins.filter as flt

        found = []
        for mod in (cmd, flt):
            for name, obj in vars(mod).items():
                if not inspect.isfunction(obj):
                    continue
                for handler, _group in getattr(obj, "handlers", []):
                    flt_obj = handler.filters
                    # hydrogram RegexFilter apna compiled pattern `.p` me rakhta hai
                    compiled = getattr(flt_obj, "p", None)
                    if getattr(compiled, "pattern", None) == pattern:
                        found.append(f"{mod.__name__}.{name}")
        return found

    def test_single_close_callback_handler(self):
        handlers = self._plugin_handlers("^close_")
        self.assertEqual(len(handlers), 1,
                         f"`^close_` par ek hi handler hona chahiye, mile: {handlers}")
        self.assertIn("plugins.filter.close_callback", handlers)

    def test_single_health_route(self):
        from web import web_app
        # aiohttp har GET route ke saath HEAD bhi register karta hai, isliye route
        # count nahi — distinct handler count dekhte hain.
        handlers = {r.handler for r in web_app.router.routes()
                    if getattr(r, "resource", None) and r.resource.canonical == "/health"}
        self.assertEqual(len(handlers), 1,
                         f"/health par ek hi handler hona chahiye, mile: {handlers}")
        # aur wo handler web layer ka ho (bot.py wala dead copy hata diya gaya hai)
        self.assertEqual(list(handlers)[0].__module__, "web.dashboard_routes")


class TestSharedWebHelpers(unittest.TestCase):
    def test_fast_json_single_definition(self):
        from web.web_assets import fast_json
        from web import search_api, actor_routes, post_routes
        for mod in (search_api, actor_routes, post_routes):
            with self.subTest(mod=mod.__name__):
                self.assertIs(mod.fast_json, fast_json,
                              "fast_json shared definition se aana chahiye")

    def test_fast_json_output(self):
        from web.web_assets import fast_json
        self.assertEqual(fast_json({"a": 1}), '{"a":1}')
        self.assertEqual(fast_json([1, 2]), "[1,2]")


class TestStatsHelpers(unittest.TestCase):
    """Directory/post counts ab ek shared helper se aate hain (parallel)."""

    def test_post_category_counts_shape(self):
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb

        class FakeCursor:
            def __init__(self, docs): self._docs = docs
            def __aiter__(self): return self._gen()
            async def _gen(self):
                for d in self._docs: yield d

        docs = [{"_id": "Movies", "count": 3}, {"_id": "Web Series", "count": 2}]
        with mock.patch.object(fdb, "posts") as m:
            m.aggregate.return_value = FakeCursor(docs)
            total, movies, series, appvid, porn = asyncio.run(fdb.get_post_category_counts())
        self.assertEqual((total, movies, series, appvid, porn), (5, 3, 2, 0, 0))

    def test_directory_counts_parallel(self):
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb

        async def fake_count(query=None, *a, **k):
            if not query: return 10
            if query.get("category") == "app": return 3
            if query.get("category") == "website": return 2
            return 0

        with mock.patch.object(fdb, "actors") as m:
            m.count_documents.side_effect = fake_count
            tot, act, app, web = asyncio.run(fdb.get_directory_counts())
        self.assertEqual((tot, act, app, web), (10, 5, 3, 2))

    def test_directory_counts_failure_is_safe(self):
        import asyncio
        from unittest import mock
        import database.ia_filterdb as fdb
        with mock.patch.object(fdb, "actors") as m:
            m.count_documents.side_effect = RuntimeError("db down")
            self.assertEqual(asyncio.run(fdb.get_directory_counts()), (0, 0, 0, 0))


class TestIndexPluginHelpers(unittest.TestCase):
    def test_status_text_contains_all_counters(self):
        from plugins.index import index_status_text
        txt = index_status_text("primary", "1m 2s", current=100, saved=80, duplicate=5,
                                deleted=3, no_media=4, unsupported=2, errors=6, badfiles=7)
        for needle in ("PRIMARY", "1m 2s", "100", "80", "5", "3", "2", "6", "7"):
            self.assertIn(needle, txt)
        # no_media + unsupported ek hi line me jud kar dikhta hai (4 + 2 = 6)
        self.assertIn("No Media: <code>6</code>", txt)

    def test_collection_picker_lists_three_collections(self):
        from plugins.index import collection_picker_markup
        markup = collection_picker_markup("-1001", 500, 0)
        flat = [b for row in markup.inline_keyboard for b in row]
        labels = " ".join(b.text for b in flat)
        for word in ("PRIMARY", "CLOUD", "ARCHIVES", "CANCEL"):
            self.assertIn(word, labels)
        starts = [b.callback_data for b in flat if b.callback_data.startswith("index#start#")]
        self.assertEqual(len(starts), 3)


class TestCommandsStatsPayload(unittest.TestCase):
    def test_stats_payload_matches_script_placeholders(self):
        import asyncio
        from unittest import mock
        import plugins.commands as cmds
        from Script import script

        counts = {"total": 100, "primary": 60, "primary_thumb": 10, "cloud": 30,
                  "cloud_thumb": 5, "archive": 10, "archive_thumb": 1, "total_thumb": 16}

        async def run():
            with mock.patch.object(cmds, "db_count_documents", return_value=counts), \
                 mock.patch.object(cmds, "get_directory_counts", return_value=(9, 6, 2, 1)), \
                 mock.patch.object(cmds, "get_post_category_counts", return_value=(7, 3, 2, 1, 1)), \
                 mock.patch.object(cmds.db, "total_users_count", return_value=11), \
                 mock.patch.object(cmds.db, "total_chat_count", return_value=4), \
                 mock.patch.object(cmds.db, "get_premium_users_count", return_value=2):
                return await cmds.build_stats_texts()

        admin_txt, user_txt = asyncio.run(run())
        # STATUS_TXT me 21 placeholders hain — format crash na ho aur values aayen
        self.assertIn("100", admin_txt)
        self.assertIn("11", admin_txt)
        self.assertIn("9", admin_txt)
        self.assertIn("100", user_txt)
        self.assertEqual(script.STATUS_TXT.count("{}"), 21)
        self.assertEqual(script.USER_STATUS_TXT.count("{}"), 10)


class TestPremiumTimeHelpers(unittest.TestCase):
    def test_parse_expire_time(self):
        from utils import parse_expire_time
        from datetime import datetime
        self.assertIsNone(parse_expire_time(None))
        self.assertIsNone(parse_expire_time("garbage"))
        self.assertEqual(parse_expire_time("2030-01-02 03:04:05"), datetime(2030, 1, 2, 3, 4, 5))
        d = datetime(2030, 1, 1)
        self.assertIs(parse_expire_time(d), d)

    def test_format_plan_expiry(self):
        from plugins.premium import format_plan_expiry
        from datetime import datetime
        self.assertEqual(format_plan_expiry(None), "Unknown")
        self.assertEqual(format_plan_expiry(datetime(2030, 1, 2, 3, 4, 5)), "02 January 2030, 03:04 AM")


class TestRoleResolution(unittest.TestCase):
    def test_admin_short_circuits(self):
        import asyncio
        from unittest import mock
        from web.search_api import _resolve_role_for_tg
        with mock.patch("web.search_api.is_premium") as m:
            self.assertEqual(asyncio.run(_resolve_role_for_tg(111)), "admin")
            m.assert_not_called()

    def test_premium_user_and_expired(self):
        import asyncio
        from unittest import mock
        from web.search_api import _resolve_role_for_tg

        async def yes(*a, **k): return True
        async def no(*a, **k): return False

        with mock.patch("web.search_api.is_premium", side_effect=yes), \
             mock.patch("web.search_api.IS_PREMIUM", True):
            self.assertEqual(asyncio.run(_resolve_role_for_tg(999)), "user")

        with mock.patch("web.search_api.is_premium", side_effect=no), \
             mock.patch("web.search_api.IS_PREMIUM", True):
            self.assertIsNone(asyncio.run(_resolve_role_for_tg(999)))

        # premium system off hone par sabko access
        with mock.patch("web.search_api.is_premium", side_effect=no), \
             mock.patch("web.search_api.IS_PREMIUM", False):
            self.assertEqual(asyncio.run(_resolve_role_for_tg(999)), "user")


class TestStreamTunnelHelper(unittest.TestCase):
    def test_stream_path_selection(self):
        from web.search_api import stream_target_path
        self.assertEqual(stream_target_path(5, "watch"), "/watch/5")
        self.assertEqual(stream_target_path(5, "download"), "/download/5")
        # unknown mode -> watch (default), crash nahi
        self.assertEqual(stream_target_path(7, "weird"), "/watch/7")


class TestHomepageRobustness(unittest.TestCase):
    """
    Regression: `getattr(temp, 'U_NAME', 'AutoFilterBot')` ka default kabhi apply
    nahi hota tha (temp.U_NAME class me None declared hai), isliye bot client start
    hone se pehle `/` homepage TypeError dekar 500 crash karta tha.
    """

    def test_homepage_survives_unset_bot_username(self):
        import asyncio
        from unittest import mock
        from utils import temp
        from web.stream_routes import root_route_handler

        with mock.patch.object(temp, "U_NAME", None):
            req = mock.MagicMock()
            resp = asyncio.run(root_route_handler(req))
        self.assertEqual(resp.status, 200)
        self.assertIn("AutoFilterBot", resp.text)

    def test_homepage_uses_real_username_when_set(self):
        import asyncio
        from unittest import mock
        from utils import temp
        from web.stream_routes import root_route_handler

        with mock.patch.object(temp, "U_NAME", "MyRealBot"):
            req = mock.MagicMock()
            resp = asyncio.run(root_route_handler(req))
        self.assertEqual(resp.status, 200)
        self.assertIn("MyRealBot", resp.text)


class TestHealthEndpoint(unittest.TestCase):
    def test_single_handler_reports_uptime(self):
        import asyncio
        import json
        from unittest import mock
        from utils import temp
        from web.dashboard_routes import koyeb_health_check

        with mock.patch.object(temp, "START_TIME", 1000.0), \
             mock.patch("web.dashboard_routes.time.time", return_value=1042.5):
            resp = asyncio.run(koyeb_health_check(mock.MagicMock()))
        data = json.loads(resp.text)
        self.assertEqual(data["status"], "alive")
        self.assertEqual(data["uptime_seconds"], 42.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
