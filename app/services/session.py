from datetime import datetime, timezone

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
        self.settings = settings

    async def ensure_indexes(self) -> None:
        await self.sessions.create_index('created_at', expireAfterSeconds=self.settings.session_ttl_seconds)
        await self.counters.create_index('date', unique=True)

    async def create_session(self, session: SessionDocument) -> str:
        await self.sessions.insert_one(session.model_dump(by_alias=True))
        return session.id

    async def get_session(self, session_id: str) -> dict | None:
        return await self.sessions.find_one({'_id': session_id})

    async def update_session(self, session_id: str, **fields: object) -> None:
        await self.sessions.update_one({'_id': session_id}, {'$set': fields})

    async def increment_daily_cap_or_reject(self) -> bool:
        today = datetime.now(timezone.utc).date().isoformat()
        doc = await self.counters.find_one_and_update(
            {'date': today, 'count': {'$lt': self.settings.max_daily_analyses}},
            {'$inc': {'count': 1}, '$setOnInsert': {'date': today}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc is not None


session_service = SessionService()
