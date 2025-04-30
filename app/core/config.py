from typing import Optional, Any
from pydantic_settings import BaseSettings
from pydantic import PostgresDsn, validator
from functools import lru_cache

class Settings(BaseSettings):
    # API Config
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Chimuelos SA AI Agent"
    
    # OpenAI Configuration (legacy)
    OPENAI_API_KEY: Optional[str] = None
    
    # Groq Configuration
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: Optional[str] = None
    
    # Anthropic (Claude) Configuration
    ANTHROPIC_API_KEY: str
    CLAUDE_MODEL: str = "claude-3-7-sonnet-20250219"
    
    # WhatsApp Cloud API Configuration
    WEBHOOK_VERIFY_TOKEN: str
    WSP_ACCESS_TOKEN: str
    WSP_PHONE_NUMBER_ID: str
    WSP_API_VERSION: str = "v22.0"
    WSP_BUSINESS_ACCOUNT_ID: str
    
    # Twilio Configuration
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_WHATSAPP_NUMBER: Optional[str] = None
    
    # Environment
    ENVIRONMENT: str = "development"
    
    # Database Configuration
    DATABASE_URL: Optional[PostgresDsn] = None
    PGDATA: Optional[str] = None
    PGDATABASE: Optional[str] = None
    PGHOST: Optional[str] = None
    PGPASSWORD: Optional[str] = None
    PGPORT: Optional[str] = None
    PGUSER: Optional[str] = None
    
    # Security
    SECRET_KEY: str = "your-secret-key-here"  # Default for development
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Make.com (Optional)
    MAKE_WEBHOOK_URL: Optional[str] = None
    MAKE_API_KEY: Optional[str] = None
    
    # Airtable (Optional)
    AIRTABLE_API_KEY: Optional[str] = None
    AIRTABLE_BASE_ID: Optional[str] = None
    
    # Redis (for rate limiting and caching)
    REDIS_URL: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "allow"  # Permite variables adicionales en el .env

    @validator("DATABASE_URL", pre=True)
    def assemble_db_connection(cls, v: Optional[str], values: dict) -> Any:
        if isinstance(v, str):
            return v
        if all(values.get(key) for key in ["PGUSER", "PGPASSWORD", "PGHOST", "PGPORT", "PGDATABASE"]):
            return PostgresDsn.build(
                scheme="postgresql+asyncpg",
                user=values.get("PGUSER"),
                password=values.get("PGPASSWORD"),
                host=values.get("PGHOST"),
                port=values.get("PGPORT"),
                path=f"/{values.get('PGDATABASE')}",
            )
        return None

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings() 