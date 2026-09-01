"""
HubSpot Master Service — FastAPI Application.

Assembles all routers, configures middleware, and manages
application lifecycle (startup/shutdown).
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import close_db, init_db
from app.routers import health, scan, normalization, maintenance, audit, credentials

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager — runs on startup and shutdown."""
    # --- Startup ---
    logger.info(f"Starting HubSpot Master Service (env={settings.APP_ENV})")

    # Initialize database tables (development only — production uses Alembic)
    if settings.APP_ENV == "development":
        try:
            init_db()
            logger.info("Database tables initialized (development mode)")
        except Exception as exc:
            logger.error(f"Database initialization failed: {exc}")

    # Ensure data directory exists
    os.makedirs(settings.DATA_DIR, exist_ok=True)

    # Check MinIO connectivity
    try:
        from app.clients.minio_client import MinIOClient
        minio = MinIOClient()
        if minio.ensure_bucket_exists():
            logger.info(f"MinIO bucket '{settings.MINIO_BUCKET}' ready")
        else:
            logger.warning("MinIO bucket check failed — uploads may not work")
    except Exception as exc:
        logger.warning(f"MinIO not reachable at startup: {exc}")

    logger.info("HubSpot Master Service started successfully")

    yield

    # --- Shutdown ---
    logger.info("Shutting down HubSpot Master Service...")
    close_db()
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="HubSpot Master Service",
    description=(
        "Extracts data from HubSpot CRM, normalizes it into clean relational tables, "
        "and uploads to shared storage. Designed to be called by a Coordinator service."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and return a clean JSON error."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)[:500]},
    )


# --- Register Routers ---
# Public/unauthenticated
app.include_router(health.router, prefix="/api", tags=["Health"])

# Authenticated endpoints
app.include_router(scan.router, prefix="/api", tags=["Scan"])
app.include_router(normalization.router, prefix="/api", tags=["Normalization"])
app.include_router(maintenance.router, prefix="/api", tags=["Maintenance"])
app.include_router(audit.router, prefix="/api", tags=["Audit"])
app.include_router(credentials.router, prefix="/api", tags=["Credentials"])


# Root endpoint
@app.get("/", include_in_schema=False)
def root():
    """Root redirect to API docs."""
    return {
        "service": "HubSpot Master Service",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/api/health",
    }
