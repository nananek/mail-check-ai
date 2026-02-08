from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """環境変数から設定を読み込むクラス"""
    
    # Database
    DATABASE_URL: str = "postgresql://mailuser:changeme@localhost:5432/mail_check"
    
    # OpenAI
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-4.1"
    
    # Discord
    DISCORD_WEBHOOK_URL: Optional[str] = None
    
    # Worker
    POLL_INTERVAL: int = 60  # seconds
    
    # Git
    GIT_AUTHOR_NAME: str = "Mail Check AI"
    GIT_AUTHOR_EMAIL: str = "ai@mailcheck.local"
    GIT_REPOS_PATH: str = "/tmp/git_repos"
    
    # Debug
    DEBUG: bool = False
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
