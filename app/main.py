from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.middleware.security import setup_security_middleware
from app.routers import checkout, export, ingest, preview, status, webhook
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


@app.get('/ping')
async def ping() -> dict[str, str]:
    """Keep-alive endpoint — frontend polls every 4 minutes to prevent Render spin-down."""
    return {'pong': 'ok'}


@app.get('/stats')
async def stats() -> JSONResponse:
    """Live social proof counter — total paid manuals generated."""
    count = await session_service.get_total_paid_count()
    return JSONResponse({'manuals_generated': count})


app.include_router(ingest.router)
app.include_router(status.router)
app.include_router(export.router)
app.include_router(checkout.router)
app.include_router(webhook.router)
app.include_router(preview.router)

app.mount('/', StaticFiles(directory='frontend', html=True), name='frontend')
