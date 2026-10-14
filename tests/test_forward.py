"""
/forward feature के tests — सभी Telegram calls fakes/mocks से होते हैं (live account/chat की ज़रूरत नहीं).

Run:  python -m unittest discover -s tests -v
"""
import asyncio
import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

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
from hydrogram.errors import (  # noqa: E402
    AuthKeyUnregistered,
    ChatForwardsRestricted,
    ChatWriteForbidden,
    FloodWait,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    SessionPasswordNeeded,
    SessionRevoked,
    UserNotParticipant,
)

import forward_service as fs  # noqa: E402
import user_client as uc  # noqa: E402

SRC = -1001111111111
DST = -1002222222222


# ─────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────
def msg(mid, **kw):
    base = dict(id=mid, empty=False, video=None, document=None, animation=None,
                video_note=None, photo=None, audio=None, voice=None)
    base.update(kw)
    return SimpleNamespace(**base)


def video(mid):
    return msg(mid, video=SimpleNamespace(file_id=f"v{mid}"))


def mp4_doc(mid):
    return msg(mid, document=SimpleNamespace(mime_type="video/mp4", file_name="clip.mp4"))


class FakeUser:
    """Telegram User client की नकल: केवल वही methods जो runner उपयोग करता है।
    `forward_messages` जान-बूझकर नहीं है — अगर code उसे call करे तो test fail होगा।"""

    def __init__(self, messages, errors=None):
        self.messages = messages              # id -> message
        self.errors = errors or {}            # id -> list of exceptions (पहले इतनी बार raise होंगे)
        self.copies = []                      # (dst, src, mid)
        self.get_calls = []                   # हर get_messages call की ids

    async def get_chat_history(self, chat_id, limit=0, **kw):
        for mid in sorted(self.messages, reverse=True)[: limit or None]:
            yield self.messages[mid]

    async def get_messages(self, chat_id, message_ids=None, **kw):
        self.get_calls.append(list(message_ids))
        return [self.messages.get(i, msg(i, empty=True)) for i in message_ids]

    async def copy_message(self, chat_id, from_chat_id, message_id, **kw):
        queue = self.errors.get(message_id)
        if queue:
            raise queue.pop(0)
        self.copies.append((chat_id, from_chat_id, message_id))
        return SimpleNamespace(id=90000 + message_id)


class MemoryStore:
    """ForwardStore का in-memory विकल्प (वही method names)।"""

    def __init__(self):
        self.copied = {}      # (src, dst, mid) -> dst_msg_id
        self.jobs = {}        # job_id -> dict
        self.counter = 0

    async def ensure_indexes(self):
        return None

    async def create_job(self, fields):
        self.counter += 1
        jid = f"job{self.counter}"
        self.jobs[jid] = dict(fields, _id=jid)
        return jid

    async def update_job(self, job_id, fields):
        self.jobs.setdefault(job_id, {"_id": job_id}).update(fields)

    async def get_job(self, job_id):
        return self.jobs.get(job_id)

    async def is_copied(self, src_id, dst_id, src_msg_id):
        return (src_id, dst_id, src_msg_id) in self.copied

    async def mark_copied(self, src_id, dst_id, src_msg_id, dst_msg_id, job_id):
        self.copied.setdefault((src_id, dst_id, src_msg_id), dst_msg_id)


def make_job(**kw):
    base = dict(admin_id=111, src_id=SRC, dst_id=DST, src_title="SRC", dst_title="DST", job_id=None)
    base.update(kw)
    return fs.ForwardJob(**base)


def run_job(job, user, store, **kw):
    delays = []

    def delay_fn():
        delays.append(1)
        return 0.0

    async def _go():
        return await fs.run_forward_job(
            job, user, store, None, delay_fn=delay_fn, retry_backoff=(0, 0, 0), **kw
        )

    result = asyncio.run(_go())
    return result, delays


# ─────────────────────────────────────────────
# 1. ADMIN RESTRICTION
# ─────────────────────────────────────────────
class TestAdminRestriction(unittest.TestCase):
    def test_is_admin(self):
        self.assertTrue(fs.is_admin(111, [111, 222]))
        self.assertTrue(fs.is_admin("222", [111, 222]))
        self.assertFalse(fs.is_admin(333, [111, 222]))
        self.assertFalse(fs.is_admin(None, [111, 222]))
        self.assertFalse(fs.is_admin("abc", [111, 222]))

    def test_admin_pm_filter_blocks_non_admin_and_groups(self):
        import plugins.forward as pf
        from hydrogram.types import Chat, Message, User

        def m(uid, ctype):
            return Message(
                id=1,
                chat=Chat(id=uid, type=ctype),
                from_user=User(id=uid, first_name="t"),
            )

        async def check(message):
            fake_client = SimpleNamespace(loop=asyncio.get_running_loop(), executor=None)
            return await pf.ADMIN_PM(fake_client, message)

        with mock.patch.object(pf, "FORWARD_ENABLED", True):
            self.assertTrue(asyncio.run(check(m(111, enums.ChatType.PRIVATE))))
            self.assertFalse(asyncio.run(check(m(999, enums.ChatType.PRIVATE))))
            self.assertFalse(asyncio.run(check(m(111, enums.ChatType.GROUP))))

    def test_callback_rejects_non_admin_and_keeps_setup(self):
        import plugins.forward as pf
        pf.SETUP.clear()
        pf.SETUP[999] = {"step": "confirm", "ts": 1e18, "dst": None, "src": None}
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=999), data="fwd#start",
            answer=mock.AsyncMock(), message=None,
        )
        asyncio.run(pf.forward_callbacks(None, query))
        query.answer.assert_awaited_once()
        self.assertTrue(query.answer.call_args.kwargs.get("show_alert"))
        self.assertIn(999, pf.SETUP)  # non-admin setup को छुआ नहीं गया
        pf.SETUP.clear()


# ─────────────────────────────────────────────
# 2. AUTHENTICATION / USER SESSION
# ─────────────────────────────────────────────
class TestUserSession(unittest.TestCase):
    def _no_db(self):
        # DB कभी छुआ न जाए
        return mock.patch.object(uc, "load_saved_session", mock.AsyncMock(return_value=None))

    def test_missing_session_asks_for_login_without_secret(self):
        with mock.patch.object(uc, "USER_SESSION_STRING", ""), \
                mock.patch.object(uc, "_runtime_session", None), self._no_db():
            self.assertFalse(uc.is_session_configured())
            with self.assertRaises(uc.UserSessionError) as cm:
                asyncio.run(uc.ensure_user_client())
            self.assertTrue(cm.exception.needs_login)
            self.assertIn("/forward", str(cm.exception))
            self.assertFalse(asyncio.run(uc.start_user_client()))

    def test_env_session_takes_precedence_over_saved(self):
        with mock.patch.object(uc, "USER_SESSION_STRING", "ENV"), \
                mock.patch.object(uc, "_runtime_session", "SAVED"):
            self.assertEqual(uc.get_session_string(), "ENV")
            self.assertEqual(uc.session_source(), "env")
        with mock.patch.object(uc, "USER_SESSION_STRING", ""), \
                mock.patch.object(uc, "_runtime_session", "SAVED"):
            self.assertEqual(uc.get_session_string(), "SAVED")
            self.assertEqual(uc.session_source(), "saved")

    def test_invalid_env_session_no_secret_and_no_auto_login(self):
        secret = "1AQAOMnotARealSessionStringXYZ=="
        fake_client = mock.AsyncMock()
        fake_client.is_connected = False
        fake_client.start.side_effect = AuthKeyUnregistered()
        with mock.patch.object(uc, "USER_SESSION_STRING", secret), \
                mock.patch.object(uc, "_build_client", return_value=fake_client):
            with self.assertRaises(uc.UserSessionError) as cm:
                asyncio.run(uc.ensure_user_client())
        self.assertNotIn(secret, str(cm.exception))
        self.assertFalse(cm.exception.needs_login)
        self.assertIsNone(uc.get_user_client())

    def test_invalid_saved_session_is_cleared_and_login_requested(self):
        fake_client = mock.AsyncMock()
        fake_client.is_connected = False
        fake_client.start.side_effect = SessionRevoked()
        clear = mock.AsyncMock()
        with mock.patch.object(uc, "USER_SESSION_STRING", ""), \
                mock.patch.object(uc, "_runtime_session", "OLDSESSION"), \
                mock.patch.object(uc, "_build_client", return_value=fake_client), \
                mock.patch.object(uc, "_clear_saved_session", clear):
            with self.assertRaises(uc.UserSessionError) as cm:
                asyncio.run(uc.ensure_user_client())
        clear.assert_awaited_once()
        self.assertTrue(cm.exception.needs_login)
        self.assertNotIn("OLDSESSION", str(cm.exception))

    def test_start_user_client_is_non_fatal(self):
        fake_client = mock.AsyncMock()
        fake_client.is_connected = False
        fake_client.start.side_effect = ConnectionError("network down")
        with mock.patch.object(uc, "USER_SESSION_STRING", "fake"), \
                mock.patch.object(uc, "_build_client", return_value=fake_client):
            self.assertFalse(asyncio.run(uc.start_user_client()))

    def test_build_client_is_in_memory_no_updates(self):
        with mock.patch.object(uc, "USER_SESSION_STRING", "fakesession"), \
                mock.patch.object(uc, "Client") as client_cls:
            uc._build_client()
        kwargs = client_cls.call_args.kwargs
        self.assertTrue(kwargs["in_memory"])
        self.assertTrue(kwargs["no_updates"])
        self.assertEqual(kwargs["session_string"], "fakesession")

    def test_phone_normalization(self):
        self.assertEqual(uc.normalize_phone(" +91 98765-43210 "), "+919876543210")
        for bad in ("9876543210", "+12", "abc", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(uc.UserSessionError):
                    uc.normalize_phone(bad)


class TestInBotLogin(unittest.TestCase):
    def setUp(self):
        uc._login.update(client=None, phone=None, hash=None)

    def tearDown(self):
        uc._login.update(client=None, phone=None, hash=None)

    def _login_client(self, sign_in=None, check_password=None, export="SESS-XYZ"):
        c = mock.AsyncMock()
        c.is_connected = True
        c.send_code.return_value = SimpleNamespace(phone_code_hash="HASH1")
        c.sign_in.side_effect = sign_in
        c.check_password.side_effect = check_password
        c.export_session_string.return_value = export
        return c

    def test_full_login_with_otp_only(self):
        client = self._login_client()
        save = mock.AsyncMock()
        with mock.patch.object(uc, "Client", return_value=client), \
                mock.patch.object(uc, "save_session", save), \
                mock.patch.object(uc, "stop_user_client", mock.AsyncMock()), \
                mock.patch.object(uc, "ensure_user_client", mock.AsyncMock()):
            asyncio.run(uc.begin_login("+919876543210"))
            self.assertTrue(uc.is_login_active())
            done = asyncio.run(uc.submit_login_code("12345"))
        self.assertTrue(done)
        client.sign_in.assert_awaited_once_with("+919876543210", "HASH1", "12345")
        save.assert_awaited_once_with("SESS-XYZ")
        self.assertFalse(uc.is_login_active())  # login client साफ़

    def test_full_login_with_2fa(self):
        client = self._login_client(sign_in=SessionPasswordNeeded(), check_password=None)
        save = mock.AsyncMock()
        with mock.patch.object(uc, "Client", return_value=client), \
                mock.patch.object(uc, "save_session", save), \
                mock.patch.object(uc, "stop_user_client", mock.AsyncMock()), \
                mock.patch.object(uc, "ensure_user_client", mock.AsyncMock()):
            asyncio.run(uc.begin_login("+919876543210"))
            self.assertFalse(asyncio.run(uc.submit_login_code("55555")))
            asyncio.run(uc.submit_login_password("my-2fa"))
        client.check_password.assert_awaited_once_with("my-2fa")
        save.assert_awaited_once_with("SESS-XYZ")

    def test_wrong_otp_keeps_login_active(self):
        client = self._login_client(sign_in=PhoneCodeInvalid())
        with mock.patch.object(uc, "Client", return_value=client):
            asyncio.run(uc.begin_login("+919876543210"))
            with self.assertRaises(uc.UserSessionError):
                asyncio.run(uc.submit_login_code("00000"))
        self.assertTrue(uc.is_login_active())

    def test_expired_otp_cancels_login(self):
        client = self._login_client(sign_in=PhoneCodeExpired())
        with mock.patch.object(uc, "Client", return_value=client):
            asyncio.run(uc.begin_login("+919876543210"))
            with self.assertRaises(uc.UserSessionError):
                asyncio.run(uc.submit_login_code("11111"))
        self.assertFalse(uc.is_login_active())

    def test_no_secret_in_error_messages(self):
        client = self._login_client(sign_in=PhoneCodeInvalid())
        with mock.patch.object(uc, "Client", return_value=client):
            asyncio.run(uc.begin_login("+919876543210"))
            with self.assertRaises(uc.UserSessionError) as cm:
                asyncio.run(uc.submit_login_code("99999"))
        self.assertNotIn("99999", str(cm.exception))

    def test_cancel_login_disconnects(self):
        client = self._login_client()
        with mock.patch.object(uc, "Client", return_value=client):
            asyncio.run(uc.begin_login("+919876543210"))
            asyncio.run(uc.cancel_login())
        self.assertFalse(uc.is_login_active())
        client.disconnect.assert_awaited()

    def test_submit_without_login_session(self):
        with self.assertRaises(uc.UserSessionError):
            asyncio.run(uc.submit_login_code("12345"))


# ─────────────────────────────────────────────
# 3. VIDEO-ONLY FILTER
# ─────────────────────────────────────────────
class TestVideoFilter(unittest.TestCase):
    def test_native_video_accepted(self):
        self.assertTrue(fs.is_forwardable_video(video(1)))

    def test_video_mime_document_accepted(self):
        self.assertTrue(fs.is_forwardable_video(mp4_doc(2)))

    def test_non_video_media_rejected(self):
        rejects = [
            msg(3, photo=SimpleNamespace()),
            msg(4, audio=SimpleNamespace()),
            msg(5, voice=SimpleNamespace()),
            msg(6, document=SimpleNamespace(mime_type="application/pdf", file_name="a.pdf")),
            msg(7, document=SimpleNamespace(mime_type="application/zip", file_name="x.zip")),
            msg(8, document=SimpleNamespace(mime_type="application/octet-stream", file_name="movie.mp4")),
            msg(9, document=SimpleNamespace(mime_type=None, file_name="clip.mkv")),
            msg(10),  # text-only
            msg(11, empty=True, video=SimpleNamespace()),
            msg(12, animation=SimpleNamespace(), document=SimpleNamespace(mime_type="video/mp4")),
            msg(13, video_note=SimpleNamespace(), video=None),
            None,
        ]
        for m in rejects:
            with self.subTest(m=m):
                self.assertFalse(fs.is_forwardable_video(m))

    def test_filename_alone_never_makes_video(self):
        self.assertFalse(fs.is_forwardable_video(
            msg(20, document=SimpleNamespace(mime_type="text/plain", file_name="holiday.mp4"))
        ))


# ─────────────────────────────────────────────
# 4. DELAY (5–20s, clamp, random)
# ─────────────────────────────────────────────
class TestDelay(unittest.TestCase):
    def test_default_range(self):
        with mock.patch.object(fs, "FORWARD_DELAY_MIN", 5), mock.patch.object(fs, "FORWARD_DELAY_MAX", 20):
            self.assertEqual(fs.get_copy_delay_range(), (5, 20))
            for _ in range(200):
                d = fs.random_copy_delay()
                self.assertGreaterEqual(d, 5)
                self.assertLessEqual(d, 20)

    def test_out_of_bounds_config_is_clamped(self):
        with mock.patch.object(fs, "FORWARD_DELAY_MIN", 0), mock.patch.object(fs, "FORWARD_DELAY_MAX", 999):
            self.assertEqual(fs.get_copy_delay_range(), (5, 20))
        with mock.patch.object(fs, "FORWARD_DELAY_MIN", 15), mock.patch.object(fs, "FORWARD_DELAY_MAX", 8):
            self.assertEqual(fs.get_copy_delay_range(), (8, 15))


# ─────────────────────────────────────────────
# 5. VALIDATION HELPERS
# ─────────────────────────────────────────────
class TestValidation(unittest.TestCase):
    def test_parse_chat_ref(self):
        self.assertEqual(fs.parse_chat_ref("-1001234567890"), -1001234567890)
        self.assertEqual(fs.parse_chat_ref(" @my_channel "), "@my_channel")
        self.assertEqual(fs.parse_chat_ref("my_channel"), "@my_channel")
        self.assertEqual(fs.parse_chat_ref("https://t.me/c/1234567890/55"), -1001234567890)
        self.assertEqual(fs.parse_chat_ref("t.me/some_group"), "@some_group")
        for bad in ("", "   ", "ab", "https://t.me/+InviteHash", "hello world!"):
            with self.subTest(bad=bad):
                with self.assertRaises(fs.ValidationError):
                    fs.parse_chat_ref(bad)

    def test_same_source_and_destination_rejected(self):
        with self.assertRaises(fs.ValidationError):
            fs.ensure_distinct_chats(SRC, SRC)
        fs.ensure_distinct_chats(SRC, DST)  # अलग हों तो ठीक

    def test_destination_permissions(self):
        S = enums.ChatMemberStatus
        T = enums.ChatType
        post_ok = SimpleNamespace(can_post_messages=True)
        post_no = SimpleNamespace(can_post_messages=False)
        perm = fs.destination_permission_error
        self.assertIsNone(perm(T.CHANNEL, S.OWNER, None, None, None))
        self.assertIsNone(perm(T.CHANNEL, S.ADMINISTRATOR, post_ok, None, None))
        self.assertIsNotNone(perm(T.CHANNEL, S.ADMINISTRATOR, post_no, None, None))
        self.assertIsNotNone(perm(T.CHANNEL, S.MEMBER, None, None, None))
        self.assertIsNotNone(perm(T.CHANNEL, S.LEFT, None, None, None))
        self.assertIsNone(perm(T.SUPERGROUP, S.ADMINISTRATOR, None, None, None))
        self.assertIsNone(perm(T.SUPERGROUP, S.MEMBER, None, None, SimpleNamespace(can_send_media_messages=True)))
        self.assertIsNotNone(perm(T.SUPERGROUP, S.MEMBER, None, None, SimpleNamespace(can_send_media_messages=False)))
        self.assertIsNotNone(perm(T.GROUP, S.RESTRICTED, None, SimpleNamespace(can_send_media_messages=False), None))
        self.assertIsNotNone(perm(T.GROUP, S.BANNED, None, None, None))

    def test_classify_errors(self):
        self.assertEqual(fs.classify_error(FloodWait(value=30)), "rate_limit")
        self.assertEqual(fs.classify_error(ChatWriteForbidden()), "stop")
        self.assertEqual(fs.classify_error(AuthKeyUnregistered()), "stop")
        self.assertEqual(fs.classify_error(ChatForwardsRestricted()), "skip")
        self.assertEqual(fs.classify_error(ConnectionError()), "network")
        self.assertEqual(fs.classify_error(TimeoutError()), "network")
        self.assertEqual(fs.classify_error(ValueError("x")), "stop")


# ─────────────────────────────────────────────
# 6. RUNNER: copy mode, scanning, duplicates, rate limits, cancel, resume
# ─────────────────────────────────────────────
class TestRunner(unittest.TestCase):
    def _messages(self):
        return {
            1: msg(1, photo=SimpleNamespace()),
            2: video(2),
            3: msg(3, document=SimpleNamespace(mime_type="application/pdf")),
            4: mp4_doc(4),
            5: msg(5, audio=SimpleNamespace()),
            6: video(6),
        }

    def test_only_videos_copied_via_copy_message(self):
        user, store = FakeUser(self._messages()), MemoryStore()
        job = make_job(job_id="j")
        result, delays = run_job(job, user, store)
        self.assertEqual(result.status, "completed")
        self.assertEqual([c[2] for c in user.copies], [2, 4, 6])
        self.assertTrue(all(c[0] == DST and c[1] == SRC for c in user.copies))
        self.assertEqual(result.copied, 3)
        self.assertEqual(len(delays), 3)  # हर सफल copy के बाद एक विराम
        self.assertEqual(result.max_id, 6)

    def test_duplicate_prevention_across_runs(self):
        user, store = FakeUser(self._messages()), MemoryStore()
        run_job(make_job(job_id="j1"), user, store)
        first_copies = len(user.copies)
        # नया job उसी src/dst पर — पहले copy हुए वीडियो दोबारा नहीं जाने चाहिए
        job2 = make_job(job_id="j2")
        result, _ = run_job(job2, user, store)
        self.assertEqual(len(user.copies), first_copies)
        self.assertEqual(result.duplicates, 3)
        self.assertEqual(result.copied, 0)

    def test_duplicate_key_is_src_dst_msgid(self):
        user, store = FakeUser({7: video(7)}), MemoryStore()
        store.copied[(SRC, DST + 1, 7)] = 1  # अलग destination → duplicate नहीं
        result, _ = run_job(make_job(job_id="j"), user, store)
        self.assertEqual(result.copied, 1)

    def test_scan_in_batches_of_200_max(self):
        messages = {i: msg(i, photo=SimpleNamespace()) for i in range(1, 451)}
        user, store = FakeUser(messages), MemoryStore()
        result, _ = run_job(make_job(job_id="j"), user, store)
        self.assertEqual(result.status, "completed")
        self.assertTrue(user.get_calls)
        self.assertTrue(all(len(ids) <= 200 for ids in user.get_calls))
        self.assertEqual(result.scanned, 450)

    def test_flood_wait_halts_job_and_resume_continues_without_resend(self):
        messages = {2: video(2), 4: video(4), 6: video(6)}
        user = FakeUser(messages, errors={4: [FloodWait(value=42)]})
        store = MemoryStore()
        job = make_job(job_id="j")
        result, _ = run_job(job, user, store)
        self.assertEqual(result.status, "floodwait")
        self.assertEqual(result.wait_seconds, 42)
        self.assertGreater(result.wait_until, 0)
        self.assertEqual([c[2] for c in user.copies], [2])   # 4 पर रुका, 6 तक नहीं गया
        self.assertEqual(result.last_scanned_id, 2)           # checkpoint 4 से पहले

        # Resume (FloodWait खत्म मान लें): 2 दोबारा नहीं, 4 और 6 भेजे जाएँ
        doc = fs.job_to_fields(result)
        resumed = fs.job_from_doc(dict(doc, _id=result.job_id))
        resumed.wait_until = 0.0
        result2, _ = run_job(resumed, user, store)
        self.assertEqual(result2.status, "completed")
        self.assertEqual([c[2] for c in user.copies], [2, 4, 6])

    def test_stop_request_halts_safely_and_checkpoint_saved(self):
        messages = {i: video(i) for i in range(1, 6)}
        user, store = FakeUser(messages), MemoryStore()
        job = make_job(job_id="j")

        def delay_fn_stop():
            job.stop_event.set()   # पहली copy के बाद stop
            return 0.0

        async def _go():
            return await fs.run_forward_job(job, user, store, None, delay_fn=delay_fn_stop,
                                            retry_backoff=(0, 0, 0))

        result = asyncio.run(_go())
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.copied, 1)
        self.assertEqual(result.last_scanned_id, 1)
        self.assertEqual(store.jobs["j"]["status"], "stopped")

    def test_non_retryable_permission_error_stops_job(self):
        messages = {2: video(2), 4: video(4)}
        user = FakeUser(messages, errors={2: [ChatWriteForbidden()]})
        result, _ = run_job(make_job(job_id="j"), user, MemoryStore())
        self.assertEqual(result.status, "error")
        self.assertEqual(result.copied, 0)
        self.assertEqual(user.copies, [])          # 4 तक नहीं पहुँचा
        self.assertIn("permission", result.error)

    def test_restricted_message_is_skipped_and_counted(self):
        messages = {2: video(2), 4: video(4)}
        user = FakeUser(messages, errors={2: [ChatForwardsRestricted()]})
        result, _ = run_job(make_job(job_id="j"), user, MemoryStore())
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.failed, 1)
        self.assertEqual([c[2] for c in user.copies], [4])

    def test_network_error_retried_then_succeeds(self):
        messages = {2: video(2)}
        user = FakeUser(messages, errors={2: [ConnectionError(), TimeoutError()]})
        result, _ = run_job(make_job(job_id="j"), user, MemoryStore())
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.copied, 1)

    def test_network_error_exhausts_retries_and_resumable(self):
        messages = {2: video(2)}
        user = FakeUser(messages, errors={2: [ConnectionError()] * 10})
        result, _ = run_job(make_job(job_id="j"), user, MemoryStore())
        self.assertEqual(result.status, "error")
        self.assertIn(result.status, fs.RESUMABLE_STATUSES)

    def test_no_forward_messages_api_used(self):
        # FakeUser में forward_messages नहीं है; copy के अलावा कुछ भी call हुआ तो job error होगा
        user, store = FakeUser({2: video(2)}), MemoryStore()
        result, _ = run_job(make_job(job_id="j"), user, store)
        self.assertEqual(result.status, "completed")
        self.assertFalse(hasattr(user, "forward_messages"))

    def test_progress_notifier_receives_updates(self):
        seen = []

        async def notify(job):
            seen.append(job.status)

        user, store = FakeUser({2: video(2)}), MemoryStore()
        job = make_job(job_id="j")

        async def _go():
            return await fs.run_forward_job(job, user, store, notify, delay_fn=lambda: 0.0,
                                            retry_backoff=(0, 0, 0), progress_interval=0)

        asyncio.run(_go())
        self.assertEqual(seen[-1], "completed")


# ─────────────────────────────────────────────
# 7. RESUME GATING & PROGRESS TEXT
# ─────────────────────────────────────────────
class TestResumeAndUI(unittest.TestCase):
    def test_resume_blocked_during_flood_wait(self):
        import time
        job = make_job(job_id="j", status="floodwait")
        job.wait_until = time.time() + 120
        self.assertIsNotNone(fs.resume_block_reason(job, time.time()))
        job.wait_until = time.time() - 1
        self.assertIsNone(fs.resume_block_reason(job, time.time()))

    def test_resume_blocked_for_completed_or_running(self):
        import time
        self.assertIsNotNone(fs.resume_block_reason(make_job(status="completed"), time.time()))
        self.assertIsNotNone(fs.resume_block_reason(make_job(status="running"), time.time()))
        self.assertIsNone(fs.resume_block_reason(make_job(status="interrupted"), time.time()))

    def test_progress_text_contains_required_fields_and_escapes(self):
        job = make_job(job_id="j", src_title="<b>evil</b>", scanned=10, copied=3, failed=1)
        text = fs.render_progress(job)
        for needle in ("Source", "Destination", "Scanned messages", "Videos copied", "Failed copies", "Status"):
            self.assertIn(needle, text)
        self.assertNotIn("<b>evil</b>", text)
        self.assertIn("&lt;b&gt;evil&lt;/b&gt;", text)

    def test_job_doc_roundtrip(self):
        job = make_job(job_id="abc", copied=5, last_scanned_id=77, max_id=100, status="stopped")
        doc = dict(fs.job_to_fields(job), _id="abc")
        back = fs.job_from_doc(doc)
        self.assertEqual((back.copied, back.last_scanned_id, back.max_id, back.status),
                         (5, 77, 100, "stopped"))

    def test_job_fields_never_contain_session_or_secrets(self):
        fields = fs.job_to_fields(make_job())
        joined = " ".join(str(v) for v in fields.values()).lower()
        for banned in ("session", "otp", "password", "hash"):
            self.assertNotIn(banned, joined)


# ─────────────────────────────────────────────
# 8. CANCEL / STOP COMMANDS & CONCURRENCY
# ─────────────────────────────────────────────
class TestCommands(unittest.TestCase):
    def test_cancel_clears_only_setup(self):
        import plugins.forward as pf
        pf.SETUP.clear()
        pf.SETUP[111] = {"step": "dest", "ts": 1e18, "dst": None, "src": None}
        message = SimpleNamespace(from_user=SimpleNamespace(id=111), reply=mock.AsyncMock())
        asyncio.run(pf.forward_cancel_cmd(None, message))
        self.assertNotIn(111, pf.SETUP)
        message.reply.assert_awaited_once()
        pf.SETUP.clear()

    def test_setup_expires(self):
        import plugins.forward as pf
        pf.SETUP.clear()
        pf.SETUP[111] = {"step": "dest", "ts": 0, "dst": None, "src": None}
        self.assertIsNone(pf._get_setup(111))
        self.assertNotIn(111, pf.SETUP)

    def test_stop_without_active_job(self):
        self.assertIsNone(fs.request_stop())
        self.assertFalse(fs.is_job_running())

    def test_second_job_rejected_while_running(self):
        async def _go():
            gate = asyncio.Event()

            async def fake_task():
                await gate.wait()

            fs._active["job"] = make_job(job_id="running")
            fs._active["task"] = asyncio.create_task(fake_task())
            try:
                self.assertTrue(fs.is_job_running())
                bot = mock.AsyncMock()
                with self.assertRaises(fs.ForwardError):
                    await fs.launch_job(bot, make_job(job_id="x"), FakeUser({}), MemoryStore())
                job = fs.request_stop()
                self.assertIsNotNone(job)
                self.assertTrue(job.stop_event.is_set())
            finally:
                gate.set()
                await fs._active["task"]
                fs._active["job"] = None
                fs._active["task"] = None

        asyncio.run(_go())

    def test_chat_access_error_messages(self):
        class Owner:
            async def get_chat(self, ref):
                return SimpleNamespace(id=DST, title="D", type=enums.ChatType.CHANNEL, permissions=None)

            async def get_chat_member(self, chat_id, who):
                raise UserNotParticipant()

        with self.assertRaises(fs.ValidationError) as cm:
            asyncio.run(fs.check_destination(Owner(), DST))
        self.assertIn("member", str(cm.exception))


# ─────────────────────────────────────────────
# 8b. FORWARD_ENABLED feature flag
# ─────────────────────────────────────────────
class TestFeatureFlag(unittest.TestCase):
    def _msg(self):
        from hydrogram.types import Chat, Message, User
        return Message(id=1, chat=Chat(id=111, type=enums.ChatType.PRIVATE),
                       from_user=User(id=111, first_name="t"))

    def test_disabled_flag_blocks_all_forward_handlers(self):
        import plugins.forward as pf
        fake_client = SimpleNamespace(executor=None)

        async def check(enabled):
            with mock.patch.object(pf, "FORWARD_ENABLED", enabled):
                fake_client.loop = asyncio.get_running_loop()
                return await pf.ADMIN_PM(fake_client, self._msg())

        self.assertTrue(asyncio.run(check(True)))
        self.assertFalse(asyncio.run(check(False)))

    def test_info_default_is_enabled(self):
        import info
        self.assertIsInstance(info.FORWARD_ENABLED, bool)


class TestLoginSteps(unittest.TestCase):
    def setUp(self):
        import plugins.forward as pf
        pf.SETUP.clear()
        self.pf = pf

    def tearDown(self):
        self.pf.SETUP.clear()

    def _msg(self, text):
        return SimpleNamespace(from_user=SimpleNamespace(id=111), text=text,
                               reply=mock.AsyncMock(), delete=mock.AsyncMock())

    def test_phone_then_otp_then_2fa_steps(self):
        pf = self.pf
        pf._set_setup(111, "login_phone")
        with mock.patch.object(pf, "begin_login", mock.AsyncMock()) as begin:
            m = self._msg("+919876543210")
            asyncio.run(pf._handle_login_input(m, pf.SETUP[111]))
            begin.assert_awaited_once_with("+919876543210")
        self.assertEqual(pf.SETUP[111]["step"], "login_otp")

        with mock.patch.object(pf, "submit_login_code", mock.AsyncMock(return_value=False)):
            m = self._msg("1 2 3 4 5")
            asyncio.run(pf._handle_login_input(m, pf.SETUP[111]))
        self.assertEqual(pf.SETUP[111]["step"], "login_pwd")
        m.delete.assert_awaited()  # OTP वाला message delete करने की कोशिश

    def test_otp_letters_rejected_without_submitting(self):
        pf = self.pf
        pf._set_setup(111, "login_otp")
        with mock.patch.object(pf, "submit_login_code", mock.AsyncMock()) as sub:
            asyncio.run(pf._handle_login_input(self._msg("abcd"), pf.SETUP[111]))
            sub.assert_not_awaited()
        self.assertEqual(pf.SETUP[111]["step"], "login_otp")

    def test_success_moves_to_destination_step(self):
        pf = self.pf
        pf._set_setup(111, "login_pwd")
        with mock.patch.object(pf, "submit_login_password", mock.AsyncMock()):
            asyncio.run(pf._handle_login_input(self._msg("my-2fa"), pf.SETUP[111]))
        self.assertEqual(pf.SETUP[111]["step"], "dest")

    def test_forward_without_session_starts_login(self):
        pf = self.pf
        from user_client import UserSessionError
        msg_ = SimpleNamespace(from_user=SimpleNamespace(id=111), reply=mock.AsyncMock())
        with mock.patch.object(pf, "ensure_user_client",
                               mock.AsyncMock(side_effect=UserSessionError("x", needs_login=True))):
            asyncio.run(pf.forward_cmd(None, msg_))
        self.assertEqual(pf.SETUP[111]["step"], "login_phone")


# ─────────────────────────────────────────────
# 9. SETUP FLOW (dest → source → summary → start) — Telegram calls mocked
# ─────────────────────────────────────────────
class TestSetupFlow(unittest.TestCase):
    def setUp(self):
        import plugins.forward as pf
        pf.SETUP.clear()
        self.pf = pf

    def tearDown(self):
        self.pf.SETUP.clear()

    def _admin_msg(self, text=None, forward_chat=None, uid=111):
        status = SimpleNamespace(edit=mock.AsyncMock())
        return SimpleNamespace(
            from_user=SimpleNamespace(id=uid),
            text=text,
            forward_from_chat=forward_chat,
            reply=mock.AsyncMock(return_value=status),
        ), status

    def test_input_without_setup_is_not_consumed(self):
        from hydrogram import StopPropagation
        msg_, _ = self._admin_msg("-1002222222222")
        # setup नहीं है → StopPropagation नहीं उठना चाहिए (pm_search आदि चलें)
        asyncio.run(self.pf.forward_setup_input(None, msg_))

    def test_full_flow_then_start_creates_job(self):
        from hydrogram import StopPropagation
        pf = self.pf
        pf._set_setup(111, "dest")
        dst = fs.ChatInfo(chat_id=DST, title="Dest", kind="CHANNEL")
        src = fs.ChatInfo(chat_id=SRC, title="Src", kind="CHANNEL", note="सदस्य")
        user = object()

        with mock.patch.object(pf, "get_user_client", return_value=user), \
                mock.patch.object(pf, "check_destination", mock.AsyncMock(return_value=dst)), \
                mock.patch.object(pf, "check_source", mock.AsyncMock(return_value=src)):
            m1, st1 = self._admin_msg(f"{DST}")
            with self.assertRaises(StopPropagation):
                asyncio.run(pf.forward_setup_input(None, m1))
            self.assertEqual(pf.SETUP[111]["step"], "source")

            m2, st2 = self._admin_msg(f"{SRC}")
            with self.assertRaises(StopPropagation):
                asyncio.run(pf.forward_setup_input(None, m2))
            self.assertEqual(pf.SETUP[111]["step"], "confirm")
            self.assertIn("Forward Summary", st2.edit.call_args.args[0])

        # Start button
        bot = mock.AsyncMock()
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=111), data="fwd#start",
            answer=mock.AsyncMock(), message=SimpleNamespace(edit=mock.AsyncMock()),
        )
        launched = {}

        async def fake_launch(client, job, user_, store=None, **kw):
            launched["job"] = job
            return job

        with mock.patch.object(pf, "ensure_user_client", mock.AsyncMock(return_value=user)), \
                mock.patch.object(pf, "launch_job", side_effect=fake_launch):
            asyncio.run(pf.forward_callbacks(bot, query))

        job = launched["job"]
        self.assertEqual((job.src_id, job.dst_id, job.admin_id), (SRC, DST, 111))
        self.assertNotIn(111, pf.SETUP)

    def test_same_source_and_destination_rejected_in_flow(self):
        from hydrogram import StopPropagation
        pf = self.pf
        pf._set_setup(111, "source")
        pf.SETUP[111]["dst"] = fs.ChatInfo(chat_id=DST, title="Dest", kind="CHANNEL")
        same = fs.ChatInfo(chat_id=DST, title="Dest", kind="CHANNEL")
        with mock.patch.object(pf, "get_user_client", return_value=object()), \
                mock.patch.object(pf, "check_source", mock.AsyncMock(return_value=same)):
            m, st = self._admin_msg(f"{DST}")
            with self.assertRaises(StopPropagation):
                asyncio.run(pf.forward_setup_input(None, m))
        self.assertEqual(pf.SETUP[111]["step"], "source")  # confirm पर नहीं गया
        self.assertIn("समान", st.edit.call_args.args[0])

    def test_invalid_input_keeps_step(self):
        from hydrogram import StopPropagation
        pf = self.pf
        pf._set_setup(111, "dest")
        with mock.patch.object(pf, "get_user_client", return_value=object()):
            m, st = self._admin_msg("hello world!!")
            with self.assertRaises(StopPropagation):
                asyncio.run(pf.forward_setup_input(None, m))
        self.assertEqual(pf.SETUP[111]["step"], "dest")
        self.assertIn("❌", st.edit.call_args.args[0])

    def test_start_refused_when_job_running(self):
        pf = self.pf
        pf.SETUP[111] = {"step": "confirm", "ts": time.time(),
                         "dst": fs.ChatInfo(DST, "D", "CHANNEL"), "src": fs.ChatInfo(SRC, "S", "CHANNEL")}
        query = SimpleNamespace(from_user=SimpleNamespace(id=111), data="fwd#start",
                                answer=mock.AsyncMock(), message=None)
        with mock.patch.object(pf, "get_active_job", return_value=object()):
            asyncio.run(pf.forward_callbacks(mock.AsyncMock(), query))
        self.assertTrue(query.answer.call_args.kwargs.get("show_alert"))


if __name__ == "__main__":
    unittest.main()
