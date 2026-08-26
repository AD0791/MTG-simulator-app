"""Health contract."""

from pydantic import BaseModel


class Health(BaseModel):
    status: str
    app: str
