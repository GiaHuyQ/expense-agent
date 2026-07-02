import os
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # --- OPENAI ----
    BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_API_KEY: SecretStr | None = None
    MODEL_NAME: str = "openai:gpt-4o-mini"
    
    # --- DATA ---
    DATA_DIR: str = "./data"

    # OPTIONAL — LangSmith tracing
    LANGSMITH_TRACING: bool = False
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGSMITH_API_KEY: SecretStr | None = None
    LANGSMITH_PROJECT: str = "expense-agent"

settings = Settings()

if settings.LANGSMITH_TRACING and settings.LANGSMITH_API_KEY:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.LANGSMITH_API_KEY.get_secret_value() 
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGSMITH_PROJECT
    os.environ["LANGSMITH_ENDPOINT"] = settings.LANGSMITH_ENDPOINT