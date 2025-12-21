import logging
import traceback
import sys
from datetime import datetime, timezone

# Configure logging to show in console
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Header, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import engine
from sessions.controller import router as sessions_router
from analysis.controller import router as analysis_router
from sessions.model import Base


# Health check response model
class HealthResponse(BaseModel):
    status: str = "healthy"
    timestamp: int = Field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp() * 1000))


# FastAPI app
app = FastAPI(
    title="Interaction Monitor API",
    version="1.0.0",
    description="REST API for receiving batched user interactions, gaze-data and analytical capabilities"
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)
app.include_router(analysis_router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    raw = await request.body()
    return JSONResponse(
        status_code=422,
        content={
            "errors": exc.errors(),
            "received_body": raw.decode("utf-8")
        },
    )


@app.on_event("startup")
async def startup():
    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse()


# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Log the full stack trace
    logger.error(f"Unhandled exception for {request.method} {request.url}")
    logger.error(f"Exception: {exc}")
    logger.error(traceback.format_exc())
    print(f"ERROR: {exc}", file=sys.stderr)
    print(traceback.format_exc(), file=sys.stderr)
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": str(exc)})
