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

"""SMS provider abstraction layer for Kisan Setu.

Provides a pluggable provider interface so that the SMS gateway can be
switched at runtime by changing the ``SMS_PROVIDER`` environment variable.

Supported providers:
    mock      – Logs to stdout/logger; never sends real SMS (default).
    twilio    – Twilio Messaging API (international, production-grade).
    msg91     – MSG91 API v5 (India, DLT-registered transactional SMS).
    fast2sms  – Fast2SMS bulk API (India, development/staging only).

All providers:
    * Use ``httpx.AsyncClient`` — no SDK dependencies beyond httpx.
    * Implement per-request timeout (``SMS_TIMEOUT_SECONDS``).
    * Return a ``ProviderResult`` dataclass; never raise directly from
      ``send()`` — errors are captured and returned so the service layer
      can log + update status without crashing the calling coroutine.
    * Never log credentials, OTPs, or raw API secrets.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Result dataclass ───────────────────────────────────────────────────────

@dataclass
class ProviderResult:
    """Outcome of a single SMS send attempt."""
    success: bool
    provider_message_id: str = ""
    # Human-readable error category (never the raw API response body)
    error_code: str = ""
    error_message: str = ""
    # The HTTP status code returned by the provider (0 = no response)
    http_status: int = 0
    # Raw provider response stored only in debug mode; redacted otherwise
    raw_response: dict[str, Any] = field(default_factory=dict)


# ── Base class ─────────────────────────────────────────────────────────────

class BaseSMSProvider(ABC):
    """Abstract base for all SMS provider adapters."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._timeout = float(getattr(settings, "SMS_TIMEOUT_SECONDS", 10))
        self._max_retries = int(getattr(settings, "SMS_MAX_RETRIES", 3))

    @abstractmethod
    async def send(self, to: str, message: str) -> ProviderResult:
        """Send an SMS to ``to`` (E.164 format, e.g. ``+919876543210``).

        Must never raise.  Capture all exceptions and return a failed
        ``ProviderResult`` so the service layer can record the failure.
        """

    async def send_with_retry(self, to: str, message: str) -> ProviderResult:
        """Wrap ``send()`` with exponential-backoff retry logic.

        Retries up to ``SMS_MAX_RETRIES`` times on transient failures
        (timeout, 5xx). Does not retry on permanent failures (4xx, auth).
        """
        last_result: ProviderResult | None = None
        for attempt in range(1, self._max_retries + 1):
            result = await self.send(to, message)
            if result.success:
                return result
            last_result = result
            # Do not retry on permanent client errors
            if result.http_status in (400, 401, 403, 404, 422):
                logger.warning(
                    "SMS permanent failure (attempt %d/%d) to %s: %s",
                    attempt, self._max_retries,
                    _mask_phone(to), result.error_code,
                )
                break
            if attempt < self._max_retries:
                backoff = 2 ** (attempt - 1)  # 1s, 2s, 4s …
                logger.info(
                    "SMS transient failure (attempt %d/%d), retrying in %ds …",
                    attempt, self._max_retries, backoff,
                )
                await asyncio.sleep(backoff)
        return last_result or ProviderResult(success=False, error_code="unknown")


def _mask_phone(phone: str) -> str:
    """Return a masked phone for safe logging, e.g. +91XXXXX43210."""
    if len(phone) >= 10:
        return phone[:-5] + "XXXXX"
    return "XXXXXXXXXXX"


# ── Mock provider (default) ────────────────────────────────────────────────

class MockSMSProvider(BaseSMSProvider):
    """Development/test provider — logs the message, never hits network.

    Enabled when ``SMS_PROVIDER=mock`` (the default).
    OTPs are written to the console so developers can complete flows
    without a real SMS provider configured.
    """

    async def send(self, to: str, message: str) -> ProviderResult:
        fake_id = f"MOCK-{abs(hash(to + message)) % 10**10:010d}"
        logger.info(
            "[SMS MOCK] TO: %s | MSG: %s",
            _mask_phone(to), message[:80] + ("…" if len(message) > 80 else ""),
        )
        # Print to stdout safely for all console encodings (e.g. Windows cp1252)
        try:
            print(f"[SMS MOCK] --- TO: {_mask_phone(to)} -------------------------------", flush=True)
            print(f"[SMS MOCK] {message}", flush=True)
            print(f"[SMS MOCK] message_id: {fake_id}", flush=True)
            print("[SMS MOCK] ----------------------------------------------------", flush=True)
        except Exception:
            try:
                safe_msg = message.encode("ascii", errors="replace").decode("ascii")
                print(f"[SMS MOCK] {safe_msg}", flush=True)
            except Exception:
                pass
        return ProviderResult(
            success=True,
            provider_message_id=fake_id,
            http_status=200,
        )


# ── Twilio provider ────────────────────────────────────────────────────────

class TwilioSMSProvider(BaseSMSProvider):
    """Twilio REST Messaging API v1.

    Required settings:
        SMS_API_KEY       → Twilio Account SID (``ACxxxxxxxx…``)
        SMS_API_SECRET    → Twilio Auth Token
        SMS_FROM_NUMBER   → Your Twilio phone number (E.164)
    """

    def __init__(self, settings: Any) -> None:
        super().__init__(settings)
        self._account_sid = settings.SMS_API_KEY
        self._auth_token  = settings.SMS_API_SECRET
        self._from_number = settings.SMS_FROM_NUMBER
        self._api_url = (
            settings.SMS_API_URL
            or f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Messages.json"
        )

    async def send(self, to: str, message: str) -> ProviderResult:
        import httpx  # Lazy import — only needed when provider is active

        if not self._account_sid or not self._auth_token:
            return ProviderResult(
                success=False,
                error_code="missing_credentials",
                error_message="Twilio Account SID or Auth Token not configured.",
            )

        payload = {"To": to, "From": self._from_number, "Body": message}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._api_url,
                    data=payload,
                    auth=(self._account_sid, self._auth_token),
                )
            http_status = resp.status_code
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}

            if http_status in (200, 201):
                sid = body.get("sid", "")
                logger.info("Twilio SMS sent to %s, sid=%s", _mask_phone(to), sid)
                return ProviderResult(
                    success=True,
                    provider_message_id=sid,
                    http_status=http_status,
                )
            else:
                code = str(body.get("code", http_status))
                msg  = body.get("message", "Unknown Twilio error")
                logger.warning(
                    "Twilio send failed to %s: http=%d code=%s",
                    _mask_phone(to), http_status, code,
                )
                return ProviderResult(
                    success=False,
                    error_code=f"twilio_{code}",
                    error_message=_safe_error(msg),
                    http_status=http_status,
                )
        except httpx.TimeoutException:
            logger.error("Twilio request timed out for %s", _mask_phone(to))
            return ProviderResult(success=False, error_code="timeout",
                                  error_message="SMS provider request timed out.")
        except Exception as exc:  # noqa: BLE001
            logger.error("Twilio unexpected error for %s: %s", _mask_phone(to), type(exc).__name__)
            return ProviderResult(success=False, error_code="provider_error",
                                  error_message="SMS provider error.")


# ── MSG91 provider ─────────────────────────────────────────────────────────

class MSG91SMSProvider(BaseSMSProvider):
    """MSG91 API v5 — Indian DLT-registered transactional SMS.

    Required settings:
        SMS_API_KEY    → MSG91 API key
        SMS_SENDER_ID  → DLT-approved sender ID (6-char, e.g. KISETU)
        SMS_API_URL    → MSG91 flow URL (default: https://api.msg91.com/api/v5/flow/)
    """

    _DEFAULT_URL = "https://api.msg91.com/api/v5/flow/"

    def __init__(self, settings: Any) -> None:
        super().__init__(settings)
        self._api_key   = settings.SMS_API_KEY
        self._sender_id = getattr(settings, "SMS_SENDER_ID", "KISETU")
        self._api_url   = settings.SMS_API_URL or self._DEFAULT_URL

    async def send(self, to: str, message: str) -> ProviderResult:
        import httpx  # Lazy import

        if not self._api_key:
            return ProviderResult(
                success=False,
                error_code="missing_credentials",
                error_message="MSG91 API key not configured.",
            )

        # Strip leading + for MSG91
        recipient = to.lstrip("+")
        headers = {"authkey": self._api_key, "content-type": "application/json"}
        payload = {
            "sender": self._sender_id,
            "route": "4",         # Transactional route
            "country": "91",
            "sms": [{"message": message, "to": [recipient]}],
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._api_url, json=payload, headers=headers)
            http_status = resp.status_code
            body: dict = {}
            try:
                body = resp.json()
            except Exception:
                pass

            if http_status == 200 and body.get("type") == "success":
                msg_id = str(body.get("message", ""))
                logger.info("MSG91 SMS sent to %s, id=%s", _mask_phone(to), msg_id)
                return ProviderResult(
                    success=True,
                    provider_message_id=msg_id,
                    http_status=http_status,
                )
            else:
                err_msg = _safe_error(str(body.get("message", "MSG91 send failed")))
                logger.warning(
                    "MSG91 send failed to %s: http=%d msg=%s",
                    _mask_phone(to), http_status, err_msg,
                )
                return ProviderResult(
                    success=False,
                    error_code=f"msg91_{http_status}",
                    error_message=err_msg,
                    http_status=http_status,
                )
        except httpx.TimeoutException:
            logger.error("MSG91 request timed out for %s", _mask_phone(to))
            return ProviderResult(success=False, error_code="timeout",
                                  error_message="SMS provider request timed out.")
        except Exception as exc:  # noqa: BLE001
            logger.error("MSG91 unexpected error for %s: %s", _mask_phone(to), type(exc).__name__)
            return ProviderResult(success=False, error_code="provider_error",
                                  error_message="SMS provider error.")


# ── Fast2SMS provider ──────────────────────────────────────────────────────

class Fast2SMSProvider(BaseSMSProvider):
    """Fast2SMS Bulk API — India development/staging.

    Required settings:
        SMS_API_KEY  → Fast2SMS authorization key
        SMS_API_URL  → Fast2SMS endpoint (default: https://www.fast2sms.com/dev/bulkV2)

    Note: Fast2SMS Quick SMS route does not require DLT registration but
    is NOT suitable for production transactional SMS in India.
    """

    _DEFAULT_URL = "https://www.fast2sms.com/dev/bulkV2"

    def __init__(self, settings: Any) -> None:
        super().__init__(settings)
        self._api_key = settings.SMS_API_KEY
        self._api_url = settings.SMS_API_URL or self._DEFAULT_URL

    async def send(self, to: str, message: str) -> ProviderResult:
        import httpx  # Lazy import

        if not self._api_key:
            return ProviderResult(
                success=False,
                error_code="missing_credentials",
                error_message="Fast2SMS API key not configured.",
            )

        # Fast2SMS expects 10-digit number without country code
        number = to.lstrip("+91").lstrip("+")[-10:]
        headers = {"authorization": self._api_key, "Content-Type": "application/json"}
        payload = {
            "route": "q",             # Quick SMS — no DLT required
            "message": message,
            "language": "english",
            "flash": 0,
            "numbers": number,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._api_url, json=payload, headers=headers)
            http_status = resp.status_code
            body: dict = {}
            try:
                body = resp.json()
            except Exception:
                pass

            if http_status == 200 and body.get("return") is True:
                msg_id = str(body.get("request_id", ""))
                logger.info("Fast2SMS sent to %s, req_id=%s", _mask_phone(to), msg_id)
                return ProviderResult(
                    success=True,
                    provider_message_id=msg_id,
                    http_status=http_status,
                )
            else:
                err_msg = _safe_error(str(body.get("message", ["Fast2SMS send failed"])))
                logger.warning(
                    "Fast2SMS send failed to %s: http=%d",
                    _mask_phone(to), http_status,
                )
                return ProviderResult(
                    success=False,
                    error_code=f"fast2sms_{http_status}",
                    error_message=err_msg,
                    http_status=http_status,
                )
        except httpx.TimeoutException:
            logger.error("Fast2SMS request timed out for %s", _mask_phone(to))
            return ProviderResult(success=False, error_code="timeout",
                                  error_message="SMS provider request timed out.")
        except Exception as exc:  # noqa: BLE001
            logger.error("Fast2SMS unexpected error for %s: %s", _mask_phone(to), type(exc).__name__)
            return ProviderResult(success=False, error_code="provider_error",
                                  error_message="SMS provider error.")


# ── Factory ────────────────────────────────────────────────────────────────

def get_provider(settings: Any) -> BaseSMSProvider:
    """Return the configured SMS provider instance.

    Selection is driven by the ``SMS_PROVIDER`` setting:
        "mock"     → MockSMSProvider   (default, no real SMS)
        "twilio"   → TwilioSMSProvider
        "msg91"    → MSG91SMSProvider
        "fast2sms" → Fast2SMSProvider

    Raises:
        ValueError: If an unsupported provider name is specified.
    """
    provider_name = getattr(settings, "SMS_PROVIDER", "mock").strip().lower()
    providers: dict[str, type[BaseSMSProvider]] = {
        "mock":     MockSMSProvider,
        "twilio":   TwilioSMSProvider,
        "msg91":    MSG91SMSProvider,
        "fast2sms": Fast2SMSProvider,
    }
    if provider_name not in providers:
        raise ValueError(
            f"Unsupported SMS_PROVIDER '{provider_name}'. "
            f"Choose from: {', '.join(providers.keys())}."
        )
    logger.info("SMS provider initialised: %s", provider_name)
    return providers[provider_name](settings)


# ── Helpers ────────────────────────────────────────────────────────────────

def _safe_error(raw: str) -> str:
    """Strip sensitive tokens from provider error messages before logging."""
    # Truncate long error strings and remove anything that looks like a key/token
    import re
    sanitised = re.sub(r"[A-Za-z0-9_\-]{20,}", "[REDACTED]", raw)
    return sanitised[:200]
