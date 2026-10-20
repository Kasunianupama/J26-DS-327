from sqlalchemy import URL, create_engine
from backend.app.core.config import get_settings


def database_url() -> URL:
    """Build a SQL Server URL for the existing DelPro / DDM instance."""
    s = get_settings()
    return URL.create(
        "mssql+pyodbc",
        username=s.database_user or None,
        password=s.database_password or None,
        host=s.database_host,
        port=s.database_port,
        database=s.database_name,
        query={
            "driver": s.database_odbc_driver,
            "Encrypt": s.database_encrypt,
            "TrustServerCertificate": s.database_trust_server_certificate,
        },
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