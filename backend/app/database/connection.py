from sqlalchemy import create_engine
from backend.app.core.config import get_settings


def database_url() -> str:
    s = get_settings()
    return f"postgresql+psycopg://{s.database_user}:{s.database_password}@{s.database_host}:{s.database_port}/{s.database_name}"


def create_database_engine():
    return create_engine(database_url(), pool_pre_ping=True)

