from datetime import datetime, timezone

from bson import Binary
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

from app.config import get_settings
from app.models.session import SessionDocument


class SessionService:
    def __init__(self) -> None:
        settings = get_settings()
        self.client = AsyncIOMotorClient(settings.mongodb_uri)
        try:
            self.db = self.client.get_default_database()
        except Exception:
            self.db = self.client['codereceipt']
        self.sessions = self.db['sessions']
        self.counters = self.db['daily_counters']
        self.pdf_store = self.db['pdf_store']
        self.customers = self.db['customers']
        self.settings = settings

    async def ensure_indexes(self) -> None:
        await self.sessions.create_index(
            'created_at', expireAfterSeconds=self.settings.session_ttl_seconds
        )
        await self.counters.create_index('date', unique=True)
        # Separate collections for paid PDFs (longer TTL) and customers
        await self.pdf_store.create_index(
            'created_at',
            expireAfterSeconds=self.settings.pdf_store_ttl_days * 86400,
        )
        await self.customers.create_index('email', unique=True)
        # Index for cache lookups
        await self.sessions.create_index([('repo_hash', 1), ('tier', 1), ('status', 1)])

    # ── Core session CRUD ─────────────────────────────────────────────────

    async def create_session(self, session: SessionDocument) -> str:
        await self.sessions.insert_one(session.model_dump(by_alias=True))
        return session.id

    async def get_session(self, session_id: str) -> dict | None:
        return await self.sessions.find_one({'_id': session_id})

    async def update_session(self, session_id: str, **fields: object) -> None:
        await self.sessions.update_one({'_id': session_id}, {'$set': fields})

    # ── Daily rate-limit counter ─────────────────────────────────────────

    async def increment_daily_cap_or_reject(self) -> bool:
        today = datetime.now(timezone.utc).date().isoformat()
        doc = await self.counters.find_one_and_update(
            {'date': today, 'count': {'$lt': self.settings.max_daily_analyses}},
            {'$inc': {'count': 1}, '$setOnInsert': {'date': today}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc is not None

    async def increment_free_daily_or_reject(self) -> bool:
        """Separate cap for free-tier analyses."""
        today = datetime.now(timezone.utc).date().isoformat()
        # $setOnInsert and $inc cannot touch the same field; initialise the
        # document with free_count=0 on insert, then let $inc do the increment.
        doc = await self.counters.find_one_and_update(
            {'date': today, 'free_count': {'$lt': self.settings.max_free_analyses_per_day}},
            {'$inc': {'free_count': 1}, '$setOnInsert': {'date': today}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc is not None

    # ── Analysis cache ───────────────────────────────────────────────────

    async def find_cached_session(self, repo_hash: str, tier: str) -> dict | None:
        """Return a previously completed session for the same repo/commit + tier."""
        return await self.sessions.find_one({
            'repo_hash': repo_hash,
            'tier': tier,
            'status': 'complete',
        })

    # ── PDF storage (paid, long TTL) ─────────────────────────────────────

    async def store_pdf(self, session_id: str, pdf_bytes: bytes, repo_name: str) -> None:
        await self.pdf_store.replace_one(
            {'_id': session_id},
            {
                '_id': session_id,
                'pdf': Binary(pdf_bytes),
                'repo_name': repo_name,
                'created_at': datetime.now(timezone.utc),
            },
            upsert=True,
        )

    async def get_pdf(self, session_id: str) -> bytes | None:
        doc = await self.pdf_store.find_one({'_id': session_id})
        return bytes(doc['pdf']) if doc else None

    # ── Customer tracking ────────────────────────────────────────────────

    async def record_customer(self, email: str, session_id: str) -> None:
        await self.customers.update_one(
            {'email': email},
            {
                '$addToSet': {'session_ids': session_id},
                '$setOnInsert': {'email': email, 'created_at': datetime.now(timezone.utc)},
            },
            upsert=True,
        )

    async def get_customer_sessions(self, email: str) -> list[str]:
        doc = await self.customers.find_one({'email': email})
        return doc.get('session_ids', []) if doc else []

    # ── Stats ────────────────────────────────────────────────────────────

    async def get_total_paid_count(self) -> int:
        return await self.pdf_store.count_documents({})


session_service = SessionService()
