"""Deployment principal (non-secret log label)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PrincipalKind(StrEnum):
    deployment_google_identity = "deployment_google_identity"


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: PrincipalKind = PrincipalKind.deployment_google_identity
