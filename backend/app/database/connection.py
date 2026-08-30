from sqlalchemy import URL, create_engine
from backend.app.core.config import get_settings


def database_url() -> URL:
    """Build a SQL Server URL for the existing delpro-sql / DDM instance.

    This does not open a connection. The API demo remains database-independent.
    """
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
    return create_engine(database_url(), pool_pre_ping=True)
