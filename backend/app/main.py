from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.api.routes import health, farms, interventions, behavior, agent, risks, predictive
from backend.app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Dairy Intelligence API", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(farms.router, prefix="/api/v1")
    app.include_router(interventions.router, prefix="/api/v1")
    app.include_router(behavior.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(risks.router, prefix="/api/v1")
    app.include_router(predictive.router, prefix="/api/v1")
    @app.get("/", tags=["system"])
    def root() -> dict[str, str]:
        return {"service": "dairy-intelligence-api", "status": "ready"}
    return app


app = create_app()
