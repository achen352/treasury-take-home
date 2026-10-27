"""Application factory. Run with: python -m app.server"""

from fastapi import FastAPI

from app.config import Settings
from app.web.middleware import DOCS_CSP, RequestContextMiddleware, SecurityHeadersMiddleware
from app.web.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()

    app = FastAPI(
        title="COLA Label Verifier",
        # API docs widen the attack surface, so they are opt-in for local development.
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    app.state.settings = settings
    # Last added runs outermost: security headers must also wrap the 500s
    # produced by RequestContextMiddleware.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        SecurityHeadersMiddleware,
        csp_overrides={"/docs": DOCS_CSP} if settings.enable_docs else None,
    )
    app.include_router(router)
    return app
