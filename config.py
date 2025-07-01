import os
from fastapi import HTTPException, Header, status
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


# Database configuration (Postgres)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/monitoring")
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


# DB session dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# Optional API Key for authorization
API_KEY = os.getenv("API_KEY")


# API key dependency
async def validate_api_key(authorization: str | None = Header(None)):
    if API_KEY:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        token = authorization.split(" ",1)[1].strip()
        if token != API_KEY:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return True
