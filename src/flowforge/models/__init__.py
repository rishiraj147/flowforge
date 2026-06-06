"""
Import every model here so they register on Base.metadata.

Alembic's autogenerate compares Base.metadata against the live DB. A model that
is never imported is invisible to Base.metadata, so its table would be silently
missing from migrations. Importing here guarantees registration.
"""

from flowforge.models.base import Base
from flowforge.models.user import User

__all__ = ["Base", "User"]