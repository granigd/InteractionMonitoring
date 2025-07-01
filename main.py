
from fastapi import FastAPI, HTTPException, Header, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from config import engine
from interactions.controller import router as interactions_router
from interactions.model import Base
from interactions.schema import HealthResponse


# FastAPI app
app = FastAPI(
    title="GLSP Interaction Monitor API",
    version="1.0.0",
    description="REST API for receiving batched GLSP user interactions"
)
app.include_router(interactions_router)


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
    # Create interactions table if it doesn't exist
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
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"error": "Internal server error"})
