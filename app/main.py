import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.core.auth.deps import NotAuthenticatedError
from app.core.auth.router import limiter
from app.core.auth.router import router as auth_router
from app.core.scheduler import start_scheduler, stop_scheduler
from app.modules.clippers.routers import accounts, clippers, payouts, settings as settings_router

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Bobby San — Clip Payout", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    app.state.limiter = limiter
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="bobby_session",
        https_only=settings.session_secure,
        same_site="lax",
        max_age=14 * 24 * 3600,
    )

    static_dir = Path(__file__).parent / "core" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(auth_router)
    app.include_router(clippers.router)
    app.include_router(accounts.router)
    app.include_router(payouts.router)
    app.include_router(settings_router.router)

    @app.exception_handler(NotAuthenticatedError)
    async def redirect_to_login(request: Request, exc: NotAuthenticatedError):
        return RedirectResponse(f"/login?next={quote(exc.next_url)}", status_code=303)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(request: Request, exc: RateLimitExceeded):
        return RedirectResponse("/login", status_code=303)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/clippers", status_code=303)

    return app


app = create_app()
