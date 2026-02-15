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
    
    # Gitea Defaults (for customer repositories)
    DEFAULT_GITEA_HOST: Optional[str] = None  # e.g., "https://gitea.example.com"
    DEFAULT_GITEA_TOKEN: Optional[str] = None
    
    # Discord Bot (チャンネル/Webhook自動作成用)
    DISCORD_BOT_TOKEN: Optional[str] = None
    DISCORD_CATEGORY_ID: Optional[str] = None

    # SMTP Relay (このシステムがSMTPサーバーとして動作)
    SMTP_RELAY_ENABLED: bool = False
    SMTP_RELAY_HOST: str = "0.0.0.0"
    SMTP_RELAY_PORT: int = 587
    SMTP_RELAY_USE_STARTTLS: bool = False
    SMTP_RELAY_TLS_CERT: Optional[str] = None
    SMTP_RELAY_TLS_KEY: Optional[str] = None

    # Debug
    DEBUG: bool = False
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
