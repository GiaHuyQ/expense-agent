from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # --- OPENAI ----
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