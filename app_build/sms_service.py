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

"""Core SMS service for Kisan Setu.

``SMSService`` is the single entry-point that all business logic (farmer
registration, procurement, payment) should call to send notifications.

Design principles:
    * All sends are fire-and-forget — the caller uses ``asyncio.create_task``
      so that a slow or unavailable SMS provider never blocks a procurement
      or payment transaction.
    * OTPs are stored as ``PBKDF2-HMAC-SHA256`` hashes — never plain text.
    * Deduplication prevents the same notification being sent twice within
      a configurable window (default 5 minutes).
    * Phone numbers are validated and normalised to E.164 (+91XXXXXXXXXX).
    * API credentials, OTP values, and secrets are never logged.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any

from sms_providers import BaseSMSProvider, ProviderResult, get_provider, _mask_phone
from sms_templates import MessageType, ReferenceType, SMSStatus, render

logger = logging.getLogger(__name__)

# Compiled regex for Indian mobile numbers (10 digits, starts 6–9)
_INDIAN_PHONE_RE = re.compile(r"^[6-9]\d{9}$")


# ── Phone utilities ────────────────────────────────────────────────────────

def validate_and_normalise_phone(phone: str) -> str:
    """Validate an Indian mobile number and return it in E.164 format.

    Accepts:
        - 10-digit string: ``9876543210``
        - Country-prefixed: ``+919876543210`` or ``919876543210``

    Returns:
        ``+91XXXXXXXXXX``

    Raises:
        ValueError: If the number is invalid.
    """
    raw = str(phone).strip()
    if raw.startswith("+91"):
        raw = raw[3:]
    elif raw.startswith("91") and len(raw) == 12:
        raw = raw[2:]
    raw = raw.lstrip("0")  # strip any accidental leading zeros

    if not _INDIAN_PHONE_RE.match(raw):
        raise ValueError(
            f"Invalid Indian mobile number: '{phone}'. "
            "Must be 10 digits starting with 6, 7, 8, or 9."
        )
    return f"+91{raw}"


def _mask_phone_local(e164: str) -> str:
    return _mask_phone(e164)


# ── OTP utilities ──────────────────────────────────────────────────────────

def _generate_otp(length: int = 6) -> str:
    """Generate a cryptographically random numeric OTP."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def _hash_otp(otp: str, salt: str) -> str:
    """Return PBKDF2-HMAC-SHA256 hash of the OTP with the given salt."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        otp.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100_000,
    )
    return dk.hex()


def _verify_otp_hash(otp: str, salt: str, stored_hash: str) -> bool:
    """Constant-time comparison of OTP hash."""
    computed = _hash_otp(otp, salt)
    return secrets.compare_digest(computed, stored_hash)


# ── SMSService ─────────────────────────────────────────────────────────────

class SMSService:
    """Production-ready SMS notification service.

    Injected with a ``DatabaseService`` instance and a provider selected
    via ``SMS_PROVIDER`` environment variable.
    """

    def __init__(self, db_service: Any, settings: Any) -> None:
        self._db = db_service
        self._settings = settings
        self._provider: BaseSMSProvider = get_provider(settings)

        # Configurable knobs
        self._otp_expiry_min: int     = int(getattr(settings, "SMS_OTP_EXPIRY_MINUTES", 5))
        self._otp_max_attempts: int   = int(getattr(settings, "SMS_OTP_MAX_ATTEMPTS", 3))
        self._otp_rate_limit: int     = int(getattr(settings, "SMS_OTP_RATE_LIMIT_PER_WINDOW", 3))
        self._otp_window_min: int     = int(getattr(settings, "SMS_OTP_RATE_LIMIT_WINDOW_MINUTES", 10))
        self._dedup_window_sec: int   = int(getattr(settings, "SMS_DEDUP_WINDOW_SECONDS", 300))
        self._system_name: str        = getattr(settings, "SYSTEM_NAME", "Kisan Setu")

    # ── Internal send ──────────────────────────────────────────────────────

    async def _send_internal(
        self,
        to_e164: str,
        message: str,
        farmer_id: str | None,
        message_type: str,
        reference_type: str | None,
        reference_id: str | None,
    ) -> dict:
        """Create DB record, call provider, update status, return record dict."""

        # 1. Deduplication check (skip OTP — every OTP must be unique)
        if message_type != MessageType.OTP and farmer_id and reference_id:
            is_dup = await self._db.check_duplicate_sms(
                farmer_id=farmer_id,
                message_type=message_type,
                reference_id=reference_id,
                window_sec=self._dedup_window_sec,
            )
            if is_dup:
                logger.info(
                    "Duplicate SMS suppressed: type=%s ref=%s farmer=%s",
                    message_type, reference_id, farmer_id,
                )
                return {"suppressed": True, "reason": "duplicate"}

        # 2. Persist PENDING record
        now = _utc_now()
        record = await self._db.create_sms_notification({
            "farmer_id":      farmer_id,
            "phone_number":   to_e164,
            "message_type":   message_type,
            "message":        message,
            "reference_type": reference_type,
            "reference_id":   reference_id,
            "status":         SMSStatus.PENDING,
            "attempt_count":  0,
            "created_at":     now,
            "updated_at":     now,
        })
        notification_id = record.get("id")

        # 3. Call provider with retry
        result: ProviderResult = await self._provider.send_with_retry(to_e164, message)

        # 4. Update status
        new_status  = SMSStatus.SENT if result.success else SMSStatus.FAILED
        sent_at     = _utc_now() if result.success else None
        error_msg   = result.error_message if not result.success else None

        await self._db.update_sms_status(
            notification_id=notification_id,
            status=new_status,
            provider_message_id=result.provider_message_id,
            error_message=error_msg,
            sent_at=sent_at,
        )

        if result.success:
            logger.info(
                "SMS sent: id=%s type=%s to=%s provider_id=%s",
                notification_id, message_type,
                _mask_phone_local(to_e164), result.provider_message_id,
            )
        else:
            logger.warning(
                "SMS failed: id=%s type=%s to=%s error=%s",
                notification_id, message_type,
                _mask_phone_local(to_e164), result.error_code,
            )

        record.update({
            "status":               new_status,
            "provider_message_id":  result.provider_message_id,
            "sent_at":              sent_at,
            "error_message":        error_msg,
        })
        return record

    # ── Public API ─────────────────────────────────────────────────────────

    async def sendSMS(
        self,
        to: str,
        message: str,
        farmer_id: str | None = None,
        message_type: str = "CUSTOM",
        reference_type: str | None = None,
        reference_id: str | None = None,
    ) -> dict:
        """Send a raw SMS message.

        Validates and normalises the phone number before sending.
        """
        to_e164 = validate_and_normalise_phone(to)
        return await self._send_internal(
            to_e164=to_e164,
            message=message,
            farmer_id=farmer_id,
            message_type=message_type,
            reference_type=reference_type,
            reference_id=reference_id,
        )

    async def sendOTP(self, phone: str, system_name: str | None = None) -> str:
        """Generate, hash, store, and send an OTP.

        Rate-limits OTP send requests per phone.

        Args:
            phone: 10-digit Indian mobile number.
            system_name: Override system name in message.

        Returns:
            Masked phone string (for UI display), e.g. ``+91XXXXX43210``.

        Raises:
            ValueError: If phone is invalid.
            PermissionError: If rate limit exceeded.
        """
        to_e164 = validate_and_normalise_phone(phone)
        phone_10 = to_e164[3:]  # strip +91

        # Rate-limit check
        recent_count = await self._db.count_otp_sends(
            phone=phone_10,
            window_sec=self._otp_window_min * 60,
        )
        if recent_count >= self._otp_rate_limit:
            logger.warning("OTP rate limit hit for %s", _mask_phone_local(to_e164))
            raise PermissionError(
                f"Too many OTP requests. Please wait {self._otp_window_min} minutes."
            )

        # Generate OTP + salt + hash
        otp   = _generate_otp()
        salt  = secrets.token_hex(16)
        otp_hash = _hash_otp(otp, salt)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(minutes=self._otp_expiry_min)
        ).isoformat()

        await self._db.store_otp(
            phone=phone_10,
            otp_hash=f"{salt}:{otp_hash}",   # store salt+hash together
            expires_at=expires_at,
        )

        # Send SMS (OTP value is NOT logged anywhere)
        sys_name = system_name or self._system_name
        message = render(
            MessageType.OTP,
            OTP=otp,
            SYSTEM_NAME=sys_name,
            EXPIRY_MINUTES=self._otp_expiry_min,
        )

        # Fire-and-forget — OTP delivery failure is noted but doesn't raise
        await self._send_internal(
            to_e164=to_e164,
            message=message,
            farmer_id=None,
            message_type=MessageType.OTP,
            reference_type=ReferenceType.OTP,
            reference_id=phone_10,
        )

        # Return masked phone for UI
        masked = f"+91{'X' * 5}{phone_10[-5:]}"
        return masked

    async def verifyOTP(self, phone: str, otp: str) -> bool:
        """Verify a submitted OTP against the stored hash.

        Args:
            phone: 10-digit Indian mobile number.
            otp:   6-digit OTP string.

        Returns:
            ``True`` if OTP is valid, not expired, and not yet used.

        Raises:
            ValueError: If phone invalid or OTP format wrong.
            PermissionError: If max attempts exceeded or OTP expired.
        """
        to_e164 = validate_and_normalise_phone(phone)
        phone_10 = to_e164[3:]

        if not otp.isdigit() or len(otp) != 6:
            raise ValueError("OTP must be exactly 6 digits.")

        record = await self._db.get_otp_record(phone=phone_10)
        if not record:
            raise PermissionError("No OTP found for this number. Please request a new one.")

        if record.get("used"):
            raise PermissionError("OTP has already been used. Please request a new one.")

        # Check expiry
        expires_at_str = record.get("expires_at", "")
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expires_at:
                raise PermissionError("OTP has expired. Please request a new one.")
        except ValueError:
            raise PermissionError("Invalid OTP record. Please request a new one.")

        # Check attempt count before incrementing
        attempts = record.get("attempt_count", 0)
        if attempts >= self._otp_max_attempts:
            raise PermissionError(
                f"Maximum OTP attempts ({self._otp_max_attempts}) exceeded. "
                "Please request a new OTP."
            )

        # Verify hash
        stored_combined = record.get("otp_hash", "")
        if ":" not in stored_combined:
            raise PermissionError("Invalid OTP record. Please request a new one.")
        salt, stored_hash = stored_combined.split(":", 1)
        is_valid = _verify_otp_hash(otp, salt, stored_hash)

        if is_valid:
            await self._db.mark_otp_used(record_id=record["id"])
            logger.info("OTP verified successfully for %s", _mask_phone_local(to_e164))
            return True
        else:
            await self._db.increment_otp_attempt(record_id=record["id"])
            remaining = self._otp_max_attempts - attempts - 1
            logger.warning(
                "OTP verification failed for %s (%d attempts remaining)",
                _mask_phone_local(to_e164), remaining,
            )
            return False

    async def sendWelcomeSMS(
        self,
        farmer_id: str,
        farmer_name: str,
        farmer_phone: str,
        registration_id: str,
    ) -> None:
        """Send welcome SMS after successful farmer registration."""
        try:
            to_e164 = validate_and_normalise_phone(farmer_phone)
            message = render(
                MessageType.WELCOME,
                SYSTEM_NAME=self._system_name,
                FARMER_NAME=farmer_name,
                FARMER_ID=registration_id,
            )
            await self._send_internal(
                to_e164=to_e164,
                message=message,
                farmer_id=farmer_id,
                message_type=MessageType.WELCOME,
                reference_type=ReferenceType.FARMER,
                reference_id=farmer_id,
            )
        except Exception as exc:
            logger.error("sendWelcomeSMS failed for farmer %s: %s", farmer_id, type(exc).__name__)

    async def sendProcurementConfirmation(
        self,
        farmer_id: str,
        farmer_name: str,
        phone: str,
        procurement_id: str,
        crop: str,
        quantity: float,
        unit: str = "Qtl",
        date: str | None = None,
    ) -> None:
        """Send SMS when a procurement/slot booking is confirmed."""
        try:
            to_e164 = validate_and_normalise_phone(phone)
            date_str = date or datetime.now().strftime("%d %b %Y")
            message = render(
                MessageType.PROCUREMENT_CREATED,
                FARMER_NAME=farmer_name,
                PROCUREMENT_ID=procurement_id,
                CROP=crop,
                QUANTITY=quantity,
                UNIT=unit,
                DATE=date_str,
            )
            await self._send_internal(
                to_e164=to_e164,
                message=message,
                farmer_id=farmer_id,
                message_type=MessageType.PROCUREMENT_CREATED,
                reference_type=ReferenceType.BOOKING,
                reference_id=procurement_id,
            )
        except Exception as exc:
            logger.error("sendProcurementConfirmation failed for %s: %s", farmer_id, type(exc).__name__)

    async def sendQualityConfirmation(
        self,
        farmer_id: str,
        farmer_name: str,
        phone: str,
        procurement_id: str,
        quantity: float,
        unit: str = "Qtl",
    ) -> None:
        """Notify farmer after quality/weight check is finalised."""
        try:
            to_e164 = validate_and_normalise_phone(phone)
            message = render(
                MessageType.QUALITY_CONFIRMED,
                FARMER_NAME=farmer_name,
                PROCUREMENT_ID=procurement_id,
                QUANTITY=quantity,
                UNIT=unit,
            )
            await self._send_internal(
                to_e164=to_e164,
                message=message,
                farmer_id=farmer_id,
                message_type=MessageType.QUALITY_CONFIRMED,
                reference_type=ReferenceType.BOOKING,
                reference_id=procurement_id,
            )
        except Exception as exc:
            logger.error("sendQualityConfirmation failed for %s: %s", farmer_id, type(exc).__name__)

    async def sendPaymentConfirmation(
        self,
        farmer_id: str,
        farmer_name: str,
        phone: str,
        procurement_id: str,
        amount: float,
        payment_reference: str,
        payment_date: str | None = None,
    ) -> None:
        """Send SMS when a PFMS payment is successfully processed.

        Security: Never include full bank account numbers or Aadhaar.
        Amount and payment reference only.
        """
        try:
            to_e164 = validate_and_normalise_phone(phone)
            date_str = payment_date or datetime.now().strftime("%d %b %Y")
            message = render(
                MessageType.PAYMENT_PROCESSED,
                FARMER_NAME=farmer_name,
                PROCUREMENT_ID=procurement_id,
                AMOUNT=f"{amount:,.2f}",
                PAYMENT_REFERENCE=payment_reference,
                DATE=date_str,
            )
            await self._send_internal(
                to_e164=to_e164,
                message=message,
                farmer_id=farmer_id,
                message_type=MessageType.PAYMENT_PROCESSED,
                reference_type=ReferenceType.VOUCHER,
                reference_id=payment_reference,
            )
        except Exception as exc:
            logger.error("sendPaymentConfirmation failed for %s: %s", farmer_id, type(exc).__name__)

    async def sendPaymentPending(
        self,
        farmer_id: str,
        farmer_name: str,
        phone: str,
        procurement_id: str,
    ) -> None:
        """Notify farmer that payment is pending."""
        try:
            to_e164 = validate_and_normalise_phone(phone)
            message = render(
                MessageType.PAYMENT_PENDING,
                FARMER_NAME=farmer_name,
                PROCUREMENT_ID=procurement_id,
            )
            await self._send_internal(
                to_e164=to_e164,
                message=message,
                farmer_id=farmer_id,
                message_type=MessageType.PAYMENT_PENDING,
                reference_type=ReferenceType.VOUCHER,
                reference_id=procurement_id,
            )
        except Exception as exc:
            logger.error("sendPaymentPending failed for %s: %s", farmer_id, type(exc).__name__)

    async def sendPaymentFailed(
        self,
        farmer_id: str,
        farmer_name: str,
        phone: str,
        procurement_id: str,
    ) -> None:
        """Notify farmer that payment has failed.

        Security: Do not include bank account details or error codes that
        expose internal system information.
        """
        try:
            to_e164 = validate_and_normalise_phone(phone)
            message = render(
                MessageType.PAYMENT_FAILED,
                FARMER_NAME=farmer_name,
                PROCUREMENT_ID=procurement_id,
            )
            await self._send_internal(
                to_e164=to_e164,
                message=message,
                farmer_id=farmer_id,
                message_type=MessageType.PAYMENT_FAILED,
                reference_type=ReferenceType.VOUCHER,
                reference_id=procurement_id,
            )
        except Exception as exc:
            logger.error("sendPaymentFailed failed for %s: %s", farmer_id, type(exc).__name__)

    async def sendStatusUpdate(
        self,
        farmer_id: str,
        farmer_name: str,
        phone: str,
        procurement_id: str,
        status: str,
    ) -> None:
        """Send a procurement status-update SMS.

        Args:
            status: One of ACCEPTED | REJECTED | UNDER_REVIEW |
                    PAYMENT_PENDING | PAYMENT_COMPLETED
        """
        _STATUS_TO_MSG_TYPE = {
            "ACCEPTED":         MessageType.STATUS_ACCEPTED,
            "REJECTED":         MessageType.STATUS_REJECTED,
            "UNDER_REVIEW":     MessageType.STATUS_UNDER_REVIEW,
            "PAYMENT_PENDING":  MessageType.STATUS_PAYMENT_PENDING,
            "PAYMENT_COMPLETED": MessageType.STATUS_PAYMENT_COMPLETED,
        }
        msg_type = _STATUS_TO_MSG_TYPE.get(status.upper())
        if not msg_type:
            logger.warning("sendStatusUpdate: unknown status '%s'", status)
            return

        try:
            to_e164 = validate_and_normalise_phone(phone)
            message = render(
                msg_type,
                FARMER_NAME=farmer_name,
                PROCUREMENT_ID=procurement_id,
            )
            await self._send_internal(
                to_e164=to_e164,
                message=message,
                farmer_id=farmer_id,
                message_type=msg_type,
                reference_type=ReferenceType.BOOKING,
                reference_id=procurement_id,
            )
        except Exception as exc:
            logger.error("sendStatusUpdate failed for %s: %s", farmer_id, type(exc).__name__)

    async def retrySMS(self, notification_id: int) -> dict:
        """Retry a FAILED SMS notification.

        Fetches the original record and re-sends using the current provider.
        """
        record = await self._db.get_sms_notification(notification_id)
        if not record:
            raise ValueError(f"SMS notification {notification_id} not found.")
        if record.get("status") not in (SMSStatus.FAILED, SMSStatus.PENDING):
            raise ValueError(
                f"Can only retry FAILED or PENDING notifications "
                f"(current status: {record.get('status')})."
            )

        # Reset to PENDING
        now = _utc_now()
        await self._db.update_sms_status(
            notification_id=notification_id,
            status=SMSStatus.PENDING,
            provider_message_id="",
            error_message=None,
            sent_at=None,
        )

        # Re-send
        to_e164 = record["phone_number"]
        message = record["message"]
        result: ProviderResult = await self._provider.send_with_retry(to_e164, message)

        new_status = SMSStatus.SENT if result.success else SMSStatus.FAILED
        await self._db.update_sms_status(
            notification_id=notification_id,
            status=new_status,
            provider_message_id=result.provider_message_id,
            error_message=result.error_message if not result.success else None,
            sent_at=_utc_now() if result.success else None,
        )

        logger.info(
            "SMS retry %s: id=%d new_status=%s",
            "succeeded" if result.success else "failed",
            notification_id, new_status,
        )
        record["status"] = new_status
        record["provider_message_id"] = result.provider_message_id
        return record

    async def listNotifications(
        self,
        farmer_id: str | None = None,
        phone: str | None = None,
        message_type: str | None = None,
        status: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Return a filtered list of SMS notification records."""
        filters = {
            "farmer_id":    farmer_id,
            "phone_number": phone,
            "message_type": message_type,
            "status":       status,
            "from_date":    from_date,
            "to_date":      to_date,
            "limit":        min(limit, 200),
            "offset":       offset,
        }
        records = await self._db.list_sms_notifications(filters)
        # Redact OTP message content for security
        for rec in records:
            if rec.get("message_type") == MessageType.OTP:
                rec["message"] = "[OTP REDACTED]"
        return records

    async def getNotification(self, notification_id: int) -> dict | None:
        """Fetch a single notification record by ID."""
        record = await self._db.get_sms_notification(notification_id)
        if record and record.get("message_type") == MessageType.OTP:
            record["message"] = "[OTP REDACTED]"
        return record

    async def updateDeliveryStatus(
        self, provider_message_id: str, delivery_status: str
    ) -> bool:
        """Update notification status from a provider delivery webhook."""
        updated = await self._db.update_sms_status_by_provider_id(
            provider_message_id=provider_message_id,
            status=delivery_status,
        )
        if updated:
            logger.info(
                "Delivery status updated: provider_id=%s status=%s",
                provider_message_id, delivery_status,
            )
        return updated


# ── Utility ────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
