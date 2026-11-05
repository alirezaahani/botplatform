"""Dependencies shared by the web routes."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from botplatform.db import session_factory


def get_session() -> Iterator[Session]:
    with session_factory()() as session:
        yield session


DbSession = Annotated[Session, Depends(get_session)]
