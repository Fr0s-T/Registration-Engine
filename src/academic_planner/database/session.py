"""SQLAlchemy engine and transaction lifecycle for the local application."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import PROJECT_ROOT, settings


class Base(DeclarativeBase):
    pass


def _resolved_url(url: str) -> str:
    prefix = "sqlite:///./"
    if url.startswith(prefix):
        path = PROJECT_ROOT / url[len(prefix):]
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path.as_posix()}"
    return url


engine = create_engine(_resolved_url(settings.database_url), future=True)


@event.listens_for(engine, "connect")
def _sqlite_foreign_keys(connection, _record):
    if settings.database_url.startswith("sqlite"):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(engine, expire_on_commit=False, class_=Session)


def get_session() -> Iterator[Session]:
    """Yield a request-scoped session for FastAPI dependency injection."""
    with SessionLocal() as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Commit one unit of work on success and roll it back on exception."""
    with SessionLocal() as session:
        with session.begin():
            yield session


def initialize_database() -> None:
    """Create any missing mapped tables without replacing Alembic migrations."""
    from . import models  # noqa: F401
    Base.metadata.create_all(engine)
