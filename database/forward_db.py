"""
💾 /forward JOB STORE (मौजूदा MongoDB connection को reuse करता है)

Collections:
- `ForwardJobs`   : job state + progress checkpoint (resume के लिए)
- `ForwardCopied` : duplicate tracking — (src_id, dst_id, src_msg_id) पर unique index
                    ताकि सफलतापूर्वक copy हुए वीडियो दोबारा न भेजे जाएँ।

⚠️ इस collection में कोई session string, OTP या password नहीं जाता।
"""

import logging

from bson.objectid import ObjectId
from pymongo.errors import DuplicateKeyError

from database.users_chats_db import get_local_now

logger = logging.getLogger(__name__)

JOBS_COLLECTION = "ForwardJobs"
COPIED_COLLECTION = "ForwardCopied"


class ForwardStore:
    def __init__(self, database):
        self.jobs = database[JOBS_COLLECTION]
        self.copied = database[COPIED_COLLECTION]

    async def ensure_indexes(self):
        await self.copied.create_index(
            [("src_id", 1), ("dst_id", 1), ("src_msg_id", 1)],
            unique=True,
            name="uniq_forward_copy",
        )
        await self.jobs.create_index([("status", 1), ("admin_id", 1)], name="forward_job_status_idx")

    # ───────── JOBS ─────────
    async def create_job(self, fields: dict) -> str:
        now = get_local_now()
        doc = dict(fields, created_at=now, updated_at=now)
        result = await self.jobs.insert_one(doc)
        return str(result.inserted_id)

    async def update_job(self, job_id: str, fields: dict):
        fields = dict(fields, updated_at=get_local_now())
        await self.jobs.update_one({"_id": ObjectId(job_id)}, {"$set": fields})

    async def get_job(self, job_id: str):
        try:
            oid = ObjectId(job_id)
        except Exception:
            return None
        return await self.jobs.find_one({"_id": oid})

    async def find_jobs_by_status(self, statuses):
        cursor = self.jobs.find({"status": {"$in": list(statuses)}})
        return await cursor.to_list(length=100)

    async def find_resumable_jobs(self, statuses, limit=3):
        cursor = self.jobs.find({"status": {"$in": list(statuses)}}).sort("updated_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    # ───────── DUPLICATE TRACKING ─────────
    async def is_copied(self, src_id: int, dst_id: int, src_msg_id: int) -> bool:
        doc = await self.copied.find_one(
            {"src_id": int(src_id), "dst_id": int(dst_id), "src_msg_id": int(src_msg_id)},
            {"_id": 1},
        )
        return doc is not None

    async def mark_copied(self, src_id, dst_id, src_msg_id, dst_msg_id, job_id):
        try:
            await self.copied.insert_one({
                "src_id": int(src_id),
                "dst_id": int(dst_id),
                "src_msg_id": int(src_msg_id),
                "dst_msg_id": dst_msg_id,
                "job_id": job_id,
                "copied_at": get_local_now(),
            })
        except DuplicateKeyError:
            # पहले से दर्ज — duplicate insert को सुरक्षित रूप से नज़रअंदाज़ करें
            logger.debug("forward copy already recorded")
