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

"""Centralised SMS message template registry for Kisan Setu.

All message text lives here — never inline in business logic.
Templates use ``{PLACEHOLDER}`` tokens and can be overridden at runtime
via environment variables (e.g. ``SMS_TEMPLATE_WELCOME``).

Security note: No template should ever include passwords, Aadhaar numbers,
full bank account numbers, or other sensitive personal information.
"""

from __future__ import annotations

import os
from typing import Any


# ── Message type constants ─────────────────────────────────────────────────
class MessageType:
    WELCOME             = "WELCOME"
    OTP                 = "OTP"
    PROCUREMENT_CREATED = "PROCUREMENT_CREATED"
    QUALITY_CONFIRMED   = "QUALITY_CONFIRMED"
    PAYMENT_PROCESSED   = "PAYMENT_PROCESSED"
    PAYMENT_PENDING     = "PAYMENT_PENDING"
    PAYMENT_FAILED      = "PAYMENT_FAILED"
    STATUS_ACCEPTED     = "STATUS_ACCEPTED"
    STATUS_REJECTED     = "STATUS_REJECTED"
    STATUS_UNDER_REVIEW = "STATUS_UNDER_REVIEW"
    STATUS_PAYMENT_PENDING   = "STATUS_PAYMENT_PENDING"
    STATUS_PAYMENT_COMPLETED = "STATUS_PAYMENT_COMPLETED"

    ALL: tuple[str, ...] = (
        WELCOME, OTP, PROCUREMENT_CREATED, QUALITY_CONFIRMED,
        PAYMENT_PROCESSED, PAYMENT_PENDING, PAYMENT_FAILED,
        STATUS_ACCEPTED, STATUS_REJECTED, STATUS_UNDER_REVIEW,
        STATUS_PAYMENT_PENDING, STATUS_PAYMENT_COMPLETED,
    )


# ── Delivery status constants ──────────────────────────────────────────────
class SMSStatus:
    PENDING   = "PENDING"
    SENT      = "SENT"
    DELIVERED = "DELIVERED"
    FAILED    = "FAILED"

    ALL: tuple[str, ...] = (PENDING, SENT, DELIVERED, FAILED)


# ── Reference type constants ───────────────────────────────────────────────
class ReferenceType:
    FARMER    = "farmer"
    BOOKING   = "booking"
    VOUCHER   = "voucher"
    OTP       = "otp"


# ── Default templates ──────────────────────────────────────────────────────
# Placeholders are written as {UPPER_SNAKE_CASE}.
# Keep each message under 160 characters when possible (single SMS unit).
# DLT-registered templates must match exactly — change via env var override.

_DEFAULTS: dict[str, str] = {
    MessageType.WELCOME: (
        "Welcome to {SYSTEM_NAME}, {FARMER_NAME}! "
        "Your Farmer ID is {FARMER_ID}. "
        "Thank you for registering with us."
    ),

    MessageType.OTP: (
        "Your OTP for {SYSTEM_NAME} is {OTP}. "
        "Valid for {EXPIRY_MINUTES} minutes. "
        "Do not share this OTP with anyone. - {SYSTEM_NAME}"
    ),

    MessageType.PROCUREMENT_CREATED: (
        "Dear {FARMER_NAME}, your procurement {PROCUREMENT_ID} "
        "for {CROP} ({QUANTITY} {UNIT}) has been recorded on {DATE}. "
        "Thank you. - {SYSTEM_NAME}"
    ),

    MessageType.QUALITY_CONFIRMED: (
        "Dear {FARMER_NAME}, quality check for procurement {PROCUREMENT_ID} "
        "is complete. Quantity confirmed: {QUANTITY} {UNIT}. "
        "- {SYSTEM_NAME}"
    ),

    MessageType.PAYMENT_PROCESSED: (
        "Dear {FARMER_NAME}, payment of Rs.{AMOUNT} for procurement "
        "{PROCUREMENT_ID} processed on {DATE}. "
        "Ref: {PAYMENT_REFERENCE}. - {SYSTEM_NAME}"
    ),

    MessageType.PAYMENT_PENDING: (
        "Dear {FARMER_NAME}, payment for procurement {PROCUREMENT_ID} "
        "is pending. We will notify you once processed. "
        "- {SYSTEM_NAME}"
    ),

    MessageType.PAYMENT_FAILED: (
        "Dear {FARMER_NAME}, payment for procurement {PROCUREMENT_ID} "
        "could not be processed. Please contact your nearest mandi office. "
        "- {SYSTEM_NAME}"
    ),

    MessageType.STATUS_ACCEPTED: (
        "Dear {FARMER_NAME}, your procurement {PROCUREMENT_ID} "
        "has been ACCEPTED. - {SYSTEM_NAME}"
    ),

    MessageType.STATUS_REJECTED: (
        "Dear {FARMER_NAME}, your procurement {PROCUREMENT_ID} "
        "has been REJECTED. Please contact your mandi officer for details. "
        "- {SYSTEM_NAME}"
    ),

    MessageType.STATUS_UNDER_REVIEW: (
        "Dear {FARMER_NAME}, your procurement {PROCUREMENT_ID} "
        "is under review. You will be notified shortly. "
        "- {SYSTEM_NAME}"
    ),

    MessageType.STATUS_PAYMENT_PENDING: (
        "Dear {FARMER_NAME}, payment for procurement {PROCUREMENT_ID} "
        "is pending verification. Expected within 2-3 working days. "
        "- {SYSTEM_NAME}"
    ),

    MessageType.STATUS_PAYMENT_COMPLETED: (
        "Dear {FARMER_NAME}, payment for procurement {PROCUREMENT_ID} "
        "has been completed. Check your bank account. "
        "- {SYSTEM_NAME}"
    ),
}

# Map MessageType → env var name for runtime override
_ENV_VAR_MAP: dict[str, str] = {
    MessageType.WELCOME:               "SMS_TEMPLATE_WELCOME",
    MessageType.OTP:                   "SMS_TEMPLATE_OTP",
    MessageType.PROCUREMENT_CREATED:   "SMS_TEMPLATE_PROCUREMENT_CREATED",
    MessageType.QUALITY_CONFIRMED:     "SMS_TEMPLATE_QUALITY_CONFIRMED",
    MessageType.PAYMENT_PROCESSED:     "SMS_TEMPLATE_PAYMENT_PROCESSED",
    MessageType.PAYMENT_PENDING:       "SMS_TEMPLATE_PAYMENT_PENDING",
    MessageType.PAYMENT_FAILED:        "SMS_TEMPLATE_PAYMENT_FAILED",
    MessageType.STATUS_ACCEPTED:       "SMS_TEMPLATE_STATUS_ACCEPTED",
    MessageType.STATUS_REJECTED:       "SMS_TEMPLATE_STATUS_REJECTED",
    MessageType.STATUS_UNDER_REVIEW:   "SMS_TEMPLATE_STATUS_UNDER_REVIEW",
    MessageType.STATUS_PAYMENT_PENDING:   "SMS_TEMPLATE_STATUS_PAYMENT_PENDING",
    MessageType.STATUS_PAYMENT_COMPLETED: "SMS_TEMPLATE_STATUS_PAYMENT_COMPLETED",
}


def _load_templates() -> dict[str, str]:
    """Load templates, applying env-var overrides where present."""
    templates: dict[str, str] = {}
    for msg_type, default in _DEFAULTS.items():
        env_val = os.getenv(_ENV_VAR_MAP.get(msg_type, ""), "").strip()
        templates[msg_type] = env_val if env_val else default
    return templates


# Module-level cache — templates are read once at import time.
# Call reload_templates() after changing env vars in tests.
_TEMPLATES: dict[str, str] = _load_templates()


def reload_templates() -> None:
    """Re-read templates from environment variables.

    Call this in tests after patching os.environ.
    """
    global _TEMPLATES
    _TEMPLATES = _load_templates()


def render(message_type: str, **kwargs: Any) -> str:
    """Render an SMS template by substituting ``{PLACEHOLDER}`` tokens.

    Args:
        message_type: One of the ``MessageType.*`` constants.
        **kwargs: Placeholder values (keys are UPPER_SNAKE_CASE).

    Returns:
        Rendered message string.

    Raises:
        KeyError: If ``message_type`` is not registered.
        ValueError: If a required placeholder is missing from ``kwargs``.
    """
    if message_type not in _TEMPLATES:
        raise KeyError(f"Unknown SMS message type: '{message_type}'")

    kwargs.setdefault("SYSTEM_NAME", os.getenv("SYSTEM_NAME", "Kisan Setu"))
    kwargs.setdefault("UNIT", "Qtl")

    template = _TEMPLATES[message_type]
    try:
        return template.format(**kwargs)
    except KeyError as exc:
        raise ValueError(
            f"Template '{message_type}' requires placeholder {exc} "
            f"which was not provided."
        ) from exc


def get_template(message_type: str) -> str:
    """Return the raw (unrendered) template string for a given type."""
    if message_type not in _TEMPLATES:
        raise KeyError(f"Unknown SMS message type: '{message_type}'")
    return _TEMPLATES[message_type]


def list_templates() -> dict[str, str]:
    """Return a copy of all registered templates."""
    return dict(_TEMPLATES)
