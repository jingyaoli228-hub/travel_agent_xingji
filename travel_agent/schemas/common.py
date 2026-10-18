"""Shared/common schema types used across research, recommendation and itinerary."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

SourceType = Literal[
    "xiaohongshu",
    "reddit",
    "google",
    "amap",
    "openstreetmap",
    "web",
    "official",
    "mock",
]


class Source(BaseModel):
    """A citation/reference for a piece of researched information.

    Kept deliberately generic so it can back a future RAG/citation layer:
    every worker output should be traceable back to a Source.
    """

    title: str = Field(..., description="Human readable title of the source")
    url: str = Field(..., description="URL of the source (mock URL for now)")
    source_type: SourceType = Field(
        default="mock", description="Where this piece of info came from"
    )
    snippet: Optional[str] = Field(
        default=None, description="Short excerpt/summary backing the claim"
    )
