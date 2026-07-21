from __future__ import annotations

from pydantic import BaseModel, Field


class LicenseActivateRequest(BaseModel):
    license_key: str = Field(min_length=1)


class CheckoutRequest(BaseModel):
    tier: str = Field(min_length=1)


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


class DeploymentConfigResponse(BaseModel):
    deployment_mode: str
