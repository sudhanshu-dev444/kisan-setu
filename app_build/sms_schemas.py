# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pydantic v2 schemas for the SMS notification API.

Follows the same strict ``model_config`` pattern used throughout the
existing Kisan Setu codebase (see schemas.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Shared validators ──────────────────────────────────────────────────────

def _validate_indian_phone(v: str) -> str:
    """Accept 10-digit numbers or E.164 (+91XXXXXXXXXX) and normalise."""
    raw = str(v).strip()
    # Strip country prefix if present
    if raw.startswith("+91"):
        raw = raw[3:]
    elif raw.startswith("91") and len(raw) == 12:
        raw = raw[2:]
    if not raw.isdigit() or len(raw) != 10:
        raise ValueError(
            "Phone number must be a valid 10-digit Indian mobile number."
        )
    if raw[0] not in "6789":
        raise ValueError(
            "Phone number must start with 6, 7, 8, or 9 (Indian mobile)."
        )
    return raw  # Return normalised 10-digit form; service layer adds +91


# ── Request schemas ────────────────────────────────────────────────────────

class SendOTPRequest(BaseModel):
    """Request body for POST /api/v1/sms/otp/send."""

    model_config = ConfigDict(strict=False, frozen=True)

    phone: str = Field(..., description="10-digit Indian mobile number.")
    system_name: str = Field(default="Kisan Setu", description="System name in the OTP message.")

    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_indian_phone(v)


class VerifyOTPRequest(BaseModel):
    """Request body for POST /api/v1/sms/otp/verify."""

    model_config = ConfigDict(strict=False, frozen=True)

    phone: str = Field(..., description="10-digit Indian mobile number.")
    otp: str = Field(..., min_length=6, max_length=6, description="6-digit OTP.")

    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_indian_phone(v)

    @field_validator("otp", mode="before")
    @classmethod
    def validate_otp(cls, v: str) -> str:
        v = str(v).strip()
        if not v.isdigit() or len(v) != 6:
            raise ValueError("OTP must be exactly 6 digits.")
        return v


class SendSMSRequest(BaseModel):
    """Request body for POST /api/v1/sms/send (admin only)."""

    model_config = ConfigDict(strict=False, frozen=True)

    phone: str = Field(..., description="10-digit Indian mobile number.")
    message_type: str = Field(..., description="One of the MessageType constants.")
    template_vars: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value pairs to substitute into the template.",
    )
    farmer_id: str | None = Field(default=None, description="Farmer ID for tracking.")
    reference_type: str | None = Field(default=None, description="booking|voucher|farmer|otp")
    reference_id: str | None = Field(default=None, description="ID of the associated record.")

    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_indian_phone(v)


# ── Response schemas ───────────────────────────────────────────────────────

class SendOTPResponse(BaseModel):
    """Response for POST /api/v1/sms/otp/send."""

    model_config = ConfigDict(strict=False, frozen=True)

    success: bool
    message: str
    expires_in_minutes: int
    # Masked phone for UI confirmation: +91XXXXX43210
    masked_phone: str


class VerifyOTPResponse(BaseModel):
    """Response for POST /api/v1/sms/otp/verify."""

    model_config = ConfigDict(strict=False, frozen=True)

    success: bool
    message: str
    # Number of verification attempts remaining (not disclosed on success)
    attempts_remaining: int | None = None


class SendSMSResponse(BaseModel):
    """Response for POST /api/v1/sms/send."""

    model_config = ConfigDict(strict=False, frozen=True)

    success: bool
    notification_id: int | None = None
    message: str
    status: str = "PENDING"


class SMSNotificationResponse(BaseModel):
    """Single SMS notification record."""

    model_config = ConfigDict(strict=False, frozen=False, populate_by_name=True)

    id: int
    farmer_id: str | None = None
    phone_number: str
    message_type: str
    # Message content is returned; OTP messages have content redacted
    message: str
    reference_type: str | None = None
    reference_id: str | None = None
    provider_message_id: str | None = None
    status: str
    attempt_count: int
    error_message: str | None = None
    sent_at: str | None = None
    created_at: str
    updated_at: str


class SMSNotificationListResponse(BaseModel):
    """Paginated list of SMS notifications."""

    model_config = ConfigDict(strict=False, frozen=True)

    notifications: list[SMSNotificationResponse]
    total: int
    page: int = 1
    limit: int


class SMSRetryResponse(BaseModel):
    """Response for POST /api/v1/sms/notifications/{id}/retry."""

    model_config = ConfigDict(strict=False, frozen=True)

    success: bool
    notification_id: int
    message: str
    new_status: str


# ── Webhook schema ─────────────────────────────────────────────────────────

class WebhookStatusUpdateRequest(BaseModel):
    """Delivery report payload from SMS provider webhook.

    Supports Twilio and MSG91 field naming conventions — fields are
    optional so the same model handles both providers.
    """

    model_config = ConfigDict(strict=False, frozen=False)

    # Twilio fields
    MessageSid: str | None = None
    MessageStatus: str | None = None   # sent | delivered | failed | undelivered

    # MSG91 fields
    requestId: str | None = None
    status: str | None = None         # delivered | failed

    # Generic fields
    provider_message_id: str | None = None
    delivery_status: str | None = None

    def resolved_message_id(self) -> str:
        """Return whichever provider message ID field is populated."""
        return (
            self.MessageSid
            or self.requestId
            or self.provider_message_id
            or ""
        )

    def resolved_status(self) -> str:
        """Normalise delivery status to DELIVERED | FAILED | SENT."""
        raw = (
            self.MessageStatus
            or self.status
            or self.delivery_status
            or ""
        ).lower()
        if raw in ("delivered",):
            return "DELIVERED"
        if raw in ("failed", "undelivered"):
            return "FAILED"
        if raw in ("sent", "queued", "sending"):
            return "SENT"
        return "SENT"
