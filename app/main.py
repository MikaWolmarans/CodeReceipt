from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.middleware.security import setup_security_middleware
from app.routers import export, ingest, status
from app.services.session import session_service

settings = get_settings()
app = FastAPI(title='CodeReceipt API')

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=False,
    allow_methods=['GET', 'POST'],
    allow_headers=['*'],
)
setup_security_middleware(app)


@app.on_event('startup')
async def startup() -> None:
    await session_service.ensure_indexes()


@app.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok'}


app.include_router(ingest.router)
app.include_router(status.router)
app.include_router(export.router)
