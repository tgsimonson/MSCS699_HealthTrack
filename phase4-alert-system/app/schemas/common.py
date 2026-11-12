"""shared request/response models"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiModel(BaseModel):
    # reject unknown fields so typos and mass-assignment attempts fail loudly
    model_config = ConfigDict(extra="forbid", from_attributes=True, use_enum_values=False)


class PageMeta(BaseModel):
    page: int = Field(ge=1, examples=[1])
    page_size: int = Field(ge=1, le=200, examples=[50])
    total_items: int = Field(ge=0, examples=[41])
    total_pages: int = Field(ge=0, examples=[1])


class Page(BaseModel, Generic[T]):
    items: list[T]
    meta: PageMeta


class FieldError(BaseModel):
    field: str = Field(examples=["readings[3].heart_rate"])
    message: str = Field(examples=["Input should be less than or equal to 300"])
    code: str = Field(examples=["less_than_equal"])


class Problem(BaseModel):
    """rfc 9457 problem details returned for every error"""

    model_config = ConfigDict(extra="allow")
    type: str = Field(examples=["https://api.healthtrack.example/problems/validation_error"])
    title: str = Field(examples=["Validation Error"])
    status: int = Field(examples=[422])
    detail: str = Field(examples=["One or more fields are invalid."])
    instance: str | None = Field(default=None, examples=["/api/v1/patients"])
    request_id: str | None = Field(default=None, examples=["2b8f0a5e-6d2c-4f7e-9a1b-3c4d5e6f7a8b"])
    errors: list[FieldError] | None = None


def problem_example(status: int, title: str, detail: str, **extra: Any) -> dict[str, Any]:
    code = title.lower().replace(" ", "_")
    return {"type": f"https://api.healthtrack.example/problems/{code}", "title": title, "status": status,
            "detail": detail, "request_id": "2b8f0a5e-6d2c-4f7e-9a1b-3c4d5e6f7a8b", **extra}
