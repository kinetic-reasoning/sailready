from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    auth_mode: str = "dev"  # dev | cognito
    dev_user_email: str = "dev@sailready.local"
    dev_user_name: str = "Dev User"
    smtp_host: str = "localhost"
    smtp_port: int = 1025


settings = Settings()
