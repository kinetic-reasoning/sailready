from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    auth_mode: str = "dev"  # dev | cognito
    dev_user_email: str = "dev@sailready.local"
    dev_user_name: str = "Dev User"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    # Temporal (POC branch): when enabled, trip lifecycle is orchestrated by a
    # durable workflow instead of the polling watcher.
    temporal_enabled: bool = False
    temporal_target: str = "temporal:7233"
    temporal_namespace: str = "default"


settings = Settings()
