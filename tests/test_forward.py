"""
/forward के pure-logic regression tests.

Ye suite plugins/forward.py ke deterministic helpers ko cover karti hai —
video filter, phone/OTP parsing, chat-ref parsing, random gap bounds —
taaki copy-engine ke rules objectively verify ho sakein (Telegram/MongoDB
ki zaroorat nahi, sab fake objects hain).

Run:  python -m unittest discover -s tests -v
"""
import os
import sys
import types
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


def fake_message(**kwargs):
    """Hydrogram Message bena ek simple namespace object."""
    return types.SimpleNamespace(**kwargs)


def fake_media(**kwargs):
    return types.SimpleNamespace(**kwargs)


class TestVideoFilter(unittest.TestCase):
    """is_video_message — sirf video files, koi aur file nahi."""

    def test_video_message_passes(self):
        from plugins.forward import is_video_message
        msg = fake_message(video=fake_media(file_id="vid"), document=None)
        self.assertTrue(is_video_message(msg))

    def test_video_document_passes(self):
        from plugins.forward import is_video_message
        doc = fake_media(mime_type="video/x-matroska", file_name="movie.mkv")
        self.assertTrue(is_video_message(fake_message(video=None, document=doc)))

    def test_octet_stream_with_video_extension_passes(self):
        from plugins.forward import is_video_message
        doc = fake_media(mime_type="application/octet-stream", file_name="Movie.MP4")
        self.assertTrue(is_video_message(fake_message(video=None, document=doc)))

    def test_non_video_files_rejected(self):
        from plugins.forward import is_video_message
        cases = [
            fake_message(video=None, document=None, text="hello"),          # text
            fake_message(video=None, document=None, photo=fake_media()),     # photo
            fake_message(video=None, document=None, audio=fake_media()),     # audio
            fake_message(video=None, document=None, sticker=fake_media()),   # sticker
            fake_message(video=None, document=None, video_note=fake_media()),  # round note
            fake_message(video=None, document=None, animation=fake_media()),   # gif
            fake_message(  # audio document
                video=None,
                document=fake_media(mime_type="audio/mpeg", file_name="song.mp3"),
            ),
            fake_message(  # apk document
                video=None,
                document=fake_media(mime_type="application/vnd.android.package-archive",
                                    file_name="app.apk"),
            ),
        ]
        for msg in cases:
            with self.subTest(msg=msg):
                self.assertFalse(is_video_message(msg))


class TestPhoneParsing(unittest.TestCase):
    """normalize_phone — international format validation."""

    def test_valid_numbers(self):
        from plugins.forward import normalize_phone
        cases = {
            "+919876543210": "+919876543210",
            "919876543210": "+919876543210",
            "+91 98765-43210": "+919876543210",
            " +1 (555) 123-4567 ": "+15551234567",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(normalize_phone(text), expected)

    def test_invalid_numbers(self):
        from plugins.forward import normalize_phone
        for text in ("", "abc", "12345", "+", "+12", "9876543210123456"):
            with self.subTest(text=text):
                self.assertIsNone(normalize_phone(text))


class TestOtpParsing(unittest.TestCase):
    """normalize_otp — sirf digits."""

    def test_plain_and_spaced(self):
        from plugins.forward import normalize_otp
        self.assertEqual(normalize_otp("12345"), "12345")
        self.assertEqual(normalize_otp("1 2 3 4 5"), "12345")
        self.assertEqual(normalize_otp("code: 98765"), "98765")

    def test_invalid(self):
        from plugins.forward import normalize_otp
        for text in ("", "abc", "12", "12345678901"):
            with self.subTest(text=text):
                self.assertIsNone(normalize_otp(text))

    def test_password_keeps_spaces(self):
        from plugins.forward import normalize_password
        self.assertEqual(normalize_password(" my pass 1 "), "my pass 1")
        self.assertIsNone(normalize_password("   "))


class TestChatRefParsing(unittest.TestCase):
    """parse_chat_ref — id / @username / t.me link."""

    def test_numeric_ids(self):
        from plugins.forward import parse_chat_ref
        self.assertEqual(parse_chat_ref("-1001234567890"), -1001234567890)
        self.assertEqual(parse_chat_ref(" 12345 "), 12345)

    def test_usernames_and_links(self):
        from plugins.forward import parse_chat_ref
        self.assertEqual(parse_chat_ref("@mychannel"), "mychannel")
        self.assertEqual(parse_chat_ref("mychannel"), "mychannel")
        self.assertEqual(parse_chat_ref("https://t.me/mychannel"), "mychannel")
        self.assertEqual(parse_chat_ref("t.me/mychannel"), "mychannel")

    def test_invalid(self):
        from plugins.forward import parse_chat_ref
        for text in ("", "hello world", "@ab", "https://t.me/", "12ab", "-"):
            with self.subTest(text=text):
                self.assertIsNone(parse_chat_ref(text))


class TestSendGap(unittest.TestCase):
    """random_gap — anti-spam safety: hamesha 5-20 second ke beech."""

    def test_gap_bounds(self):
        from plugins.forward import random_gap, SEND_GAP_MIN, SEND_GAP_MAX
        for _ in range(200):
            gap = random_gap()
            self.assertGreaterEqual(gap, SEND_GAP_MIN)
            self.assertLessEqual(gap, SEND_GAP_MAX)

    def test_mask_phone_hides_middle(self):
        from plugins.forward import mask_phone
        masked = mask_phone("+919876543210")
        self.assertTrue(masked.startswith("+919"))
        self.assertTrue(masked.endswith("210"))
        self.assertNotIn("8765432", masked)


class _FakeStatus:
    def __init__(self):
        self.edits = []

    async def edit(self, text):
        self.edits.append(text)


class _FakeMessage:
    def __init__(self):
        self.replies = []
        self.status = _FakeStatus()
        self._first = True

    async def reply(self, text):
        self.replies.append(text)
        if self._first:
            self._first = False
            return self.status
        return _FakeStatus()


class _FakeUser:
    """run_copy_job ke liye fake user-client — history + send record karta hai."""

    def __init__(self, messages):
        self.messages = {m.id: m for m in messages}
        self.order = sorted(self.messages, reverse=True)  # history: nayi → purani
        self.sent = []

    async def get_chat_history(self, src):
        for mid in self.order:
            yield self.messages[mid]

    async def get_messages(self, src, mid):
        return self.messages[mid]

    async def send_cached_media(self, dest, file_id, caption="", **kw):
        self.sent.append((file_id, caption))
        return fake_message(id=999)


class TestCopyLoop(unittest.TestCase):
    """run_copy_job — sirf video, purane→naye kram, caption safe, gap ke saath."""

    def _msgs(self):
        vid1 = fake_message(id=1, empty=False,
                            video=fake_media(file_id="V1"), document=None,
                            caption="pehla", caption_entities=["e1"])
        photo = fake_message(id=2, empty=False, video=None, document=None)
        vid3 = fake_message(id=3, empty=False,
                            video=None,
                            document=fake_media(file_id="V3", mime_type="video/mp4",
                                                file_name="b.mp4"),
                            caption=None, caption_entities=None)
        text = fake_message(id=4, empty=False, video=None, document=None)
        vid5 = fake_message(id=5, empty=False,
                            video=fake_media(file_id="V5"), document=None,
                            caption="", caption_entities=None)
        return [vid1, photo, vid3, text, vid5]

    def test_only_videos_oldest_first_with_gaps(self):
        import asyncio
        from unittest import mock
        import plugins.forward as pf

        user = _FakeUser(self._msgs())
        message = _FakeMessage()
        gaps = []

        async def fake_gap_sleep(sec):
            gaps.append(sec)

        with mock.patch.object(pf, "random_gap", return_value=5), \
             mock.patch.object(pf, "interruptible_sleep", side_effect=fake_gap_sleep):
            asyncio.run(pf.run_copy_job(None, message, user, -1001, -1002))

        # sirf 3 video gaye, woh bhi purane→naye kram me (1 → 3 → 5)
        self.assertEqual([f for f, _ in user.sent], ["V1", "V3", "V5"])
        # photo/text skip — koi aur file nahi
        self.assertEqual(len(user.sent), 3)
        # har video ke baad ek gap (anti-spam 5-20s)
        self.assertEqual(gaps, [5, 5, 5])
        # caption + entities barqarar (send_cached_media ko milti hain)
        self.assertEqual(user.sent[0][1], "pehla")

    def test_empty_source_reports_no_video(self):
        import asyncio
        from unittest import mock
        import plugins.forward as pf

        user = _FakeUser([fake_message(id=1, empty=False, video=None, document=None)])
        message = _FakeMessage()

        async def no_sleep(sec):
            pass

        with mock.patch.object(pf, "random_gap", return_value=0), \
             mock.patch.object(pf, "interruptible_sleep", side_effect=no_sleep):
            asyncio.run(pf.run_copy_job(None, message, user, -1001, -1002))

        self.assertEqual(user.sent, [])
        self.assertIn("कोई वीडियो फाइल नहीं मिली", message.replies[-1] + message.status.edits[-1])

    def test_stop_halts_loop(self):
        import asyncio
        from unittest import mock
        import plugins.forward as pf

        user = _FakeUser(self._msgs())
        message = _FakeMessage()
        pf.state.cancel = False

        async def cancel_after_first(sec):
            pf.state.cancel = True

        try:
            with mock.patch.object(pf, "random_gap", return_value=5), \
                 mock.patch.object(pf, "interruptible_sleep", side_effect=cancel_after_first):
                asyncio.run(pf.run_copy_job(None, message, user, -1001, -1002))
            # pehli file ke baad cancel → sirf 1 bheji
            self.assertEqual(len(user.sent), 1)
        finally:
            pf.state.cancel = False


if __name__ == "__main__":
    unittest.main()
