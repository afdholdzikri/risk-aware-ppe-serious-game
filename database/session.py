"""PostgreSQL-compatible SQLAlchemy connection factory."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from database.log import default_database_url


def make_engine(database_url: str | None = None) -> Engine:
    """Create a pooled engine without opening a connection immediately."""
    url = database_url or default_database_url()
    return create_engine(url, pool_pre_ping=True)
