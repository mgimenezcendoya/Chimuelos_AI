from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from sqlalchemy.engine.url import URL

# Create database URL
db_url = URL.create(
    drivername="postgresql+asyncpg",
    username=settings.PGUSER,
    password=settings.PGPASSWORD,
    host=settings.PGHOST,
    port=settings.PGPORT,
    database=settings.PGDATABASE
)

# Create async engine
engine = create_async_engine(
    db_url,
    echo=True if settings.ENVIRONMENT == "development" else False,
    future=True
)

# Create async session factory
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close() 