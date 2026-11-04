"""Dependencies shared by the web routes."""

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from botplatform.db import session_factory


def get_session() -> Iterator[Session]:
    with session_factory()() as session:
        yield session


DbSession = Annotated[Session, Depends(get_session)]


def parse_id(value: str, message: str = "No such run") -> uuid.UUID:
    """An ID in a URL that is not a UUID names nothing, so it is a 404 like an unknown one."""
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(404, message) from None
