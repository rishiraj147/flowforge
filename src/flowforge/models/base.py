"""
Declarative base — the parent class every ORM model inherits from.

SQLAlchemy collects every subclass of Base into Base.metadata, which is the
in-Python description of all your tables. Alembic reads this same metadata to
figure out what migrations to generate.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """All models inherit from this. One Base per app = one metadata registry."""
    pass