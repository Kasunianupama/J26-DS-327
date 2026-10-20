from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    frontend_url: str = "http://localhost:5173"

    # Existing SQL Server configuration
    database_host: str = "localhost"
    database_port: int = 1433
    database_name: str = "master"
    database_user: str = ""
    database_password: str = ""
    database_odbc_driver: str = "ODBC Driver 18 for SQL Server"
    database_encrypt: str = "yes"
    database_trust_server_certificate: str = "no"

    # Shared Farm X PostgreSQL configuration
    app_db_host: str = "localhost"
    app_db_port: int = 5433
    app_db_name: str = "farmx_app"
    app_db_api_user: str = ""
    app_db_api_password: str = ""
    app_db_c13_user: str = ""
    app_db_c13_password: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()