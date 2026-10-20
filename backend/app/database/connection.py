from sqlalchemy import URL, create_engine
from backend.app.core.config import Settings, get_settings


def database_url(settings: Settings | None = None) -> URL:
    """Build a PostgreSQL URL for the farmx_app database as the farmx_api role.

    This does not open a connection. The API demo remains database-independent.
    """
    s = settings or get_settings()
    return URL.create(
        "postgresql+psycopg",
        username=s.app_db_api_user or None,
        password=s.app_db_api_password or None,
        host=s.app_db_host,
        port=s.app_db_port,
        database=s.app_db_name,
    )


def create_database_engine():
    """Create the existing SQL Server engine."""
    return create_engine(database_url(), pool_pre_ping=True)


def app_database_url() -> URL:
    """Build a PostgreSQL URL for the shared Farm X application database."""
    s = get_settings()
    return URL.create(
        "postgresql+psycopg",
        username=s.app_db_api_user,
        password=s.app_db_api_password,
        host=s.app_db_host,
        port=s.app_db_port,
        database=s.app_db_name,
    )


def create_app_database_engine():
    """Create the PostgreSQL engine using the API's restricted database role."""
    return create_engine(app_database_url(), pool_pre_ping=True)