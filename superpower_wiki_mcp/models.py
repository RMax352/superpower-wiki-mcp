"""Pydantic v2 input validation models for Superpower Wiki MCP."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResponseFormat(str, Enum):
    """Supported output formats for tool responses."""

    MARKDOWN = "markdown"
    JSON = "json"


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )


class SearchPowersInput(_StrictModel):
    query: str = Field(..., min_length=1, max_length=200, description="Search query (power name, concept, or keyword).")
    limit: int = Field(default=15, ge=1, le=50, description="Maximum number of results to return.")
    offset: int = Field(default=0, ge=0, le=500, description="Pagination offset.")
    include_fanon: bool = Field(default=False, description="Include Fanon (namespace 116) pages.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetPowerInput(_StrictModel):
    title: str = Field(..., min_length=1, max_length=200, description="Power title or alias (e.g., 'Fire Manipulation', 'Pyrokinesis').")
    sections: Optional[List[str]] = Field(default=None, description="Optional list of section names to include.")
    include_known_users: bool = Field(default=False, description="Include the Known Users section (often very large).")
    max_chars: int = Field(default=12000, ge=500, le=40000, description="Maximum character budget for rendered content.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetSectionInput(_StrictModel):
    title: str = Field(..., min_length=1, max_length=200, description="Power title or alias.")
    section: str = Field(..., min_length=1, max_length=120, description="Section name or index (e.g., 'Known Users', 'Levels', 'Limitations').")
    max_chars: int = Field(default=8000, ge=500, le=40000, description="Maximum character budget for the returned section.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class ExploreTreeInput(_StrictModel):
    title: str = Field(..., min_length=1, max_length=200, description="Root power title or alias.")
    branches: List[str] = Field(
        default_factory=lambda: ["Applications", "Techniques", "Variations", "Combinations", "Associations"],
        min_length=1,
        max_length=10,
        description="Tree sections to extract internal power links from.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetLimitationsInput(_StrictModel):
    titles: List[str] = Field(..., min_length=1, max_length=5, description="List of 1 to 5 power titles.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("titles")
    @classmethod
    def _clean_titles(cls, values: List[str]) -> List[str]:
        cleaned = [v.strip() for v in values if v and v.strip()]
        if not cleaned:
            raise ValueError("Provide at least one non-empty power title.")
        return cleaned


class BrowseCategoryInput(_StrictModel):
    category: str = Field(..., min_length=1, max_length=200, description="Category name (with or without 'Category:' prefix).")
    limit: int = Field(default=25, ge=1, le=100, description="Maximum items to return per page.")
    continue_token: Optional[str] = Field(default=None, description="Pagination cursor (cmcontinue) from a previous call.")
    include_subcategories: bool = Field(default=True, description="Include subcategories alongside powers.")
    include_fanon: bool = Field(default=False, description="Include Fanon (namespace 116) pages.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class RandomPowersInput(_StrictModel):
    count: int = Field(default=3, ge=1, le=10, description="Number of random powers to draw (1 to 10).")
    category: Optional[str] = Field(default=None, max_length=200, description="Optional category to draw random powers from.")
    include_summary: bool = Field(default=True, description="Include a concise Capabilities summary for each drawn power.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class ComparePowersInput(_StrictModel):
    titles: List[str] = Field(..., min_length=2, max_length=4, description="List of 2 to 4 power titles to compare.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("titles")
    @classmethod
    def _clean_titles(cls, values: List[str]) -> List[str]:
        cleaned = [v.strip() for v in values if v and v.strip()]
        if len(cleaned) < 2:
            raise ValueError("Provide at least 2 non-empty power titles to compare.")
        return cleaned
