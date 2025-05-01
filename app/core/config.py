from typing import Optional, Any
from pydantic_settings import BaseSettings
from pydantic import PostgresDsn, validator
from functools import lru_cache

class Settings(BaseSettings):
    # API Config
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Chimuelos SA AI Agent"
    
    # Database
    DATABASE_URL: PostgresDsn
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # OpenAI
    OPENAI_API_KEY: str
    GPT_MODEL: str = "gpt-4"
    
    # Twilio
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_PHONE_NUMBER: str
    
    # Make.com
    MAKE_WEBHOOK_URL: str
    MAKE_API_KEY: str
    
    # Airtable
    AIRTABLE_API_KEY: str
    AIRTABLE_BASE_ID: str
    
    # Redis (for rate limiting and caching)
    REDIS_URL: Optional[str] = None
    
    # Environment
    ENVIRONMENT: str = "development"
    
    class Config:
        env_file = ".env"
        case_sensitive = True

    @validator("DATABASE_URL", pre=True)
    def assemble_db_connection(cls, v: Optional[str], values: dict) -> Any:
        if isinstance(v, str):
            return v
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            user=values.get("POSTGRES_USER"),
            password=values.get("POSTGRES_PASSWORD"),
            host=values.get("POSTGRES_SERVER"),
            path=f"/{values.get('POSTGRES_DB') or ''}",
        )

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings() 