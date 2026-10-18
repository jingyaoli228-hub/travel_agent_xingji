"""Schemas for the Review stage (rule-based validator + LLM reviewer)."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class DimensionScores(BaseModel):
    time_feasibility: int = Field(..., ge=0, le=100, description="时间可行性")
    route_efficiency: int = Field(..., ge=0, le=100, description="路线效率")
    preference_match: int = Field(..., ge=0, le=100, description="偏好匹配度")
    richness: int = Field(..., ge=0, le=100, description="行程丰富度")
    budget: int = Field(..., ge=0, le=100, description="预算符合度")


class ReviewReport(BaseModel):
    score: int = Field(..., ge=0, le=100)
    passed: bool
    dimension_scores: DimensionScores
    issues: List[str] = Field(default_factory=list)
    revision_instruction: List[str] = Field(default_factory=list)
    loop_count: int = Field(default=0, description="当前是第几次评审循环")
