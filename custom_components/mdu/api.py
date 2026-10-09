"""Client for Montana-Dakota Utilities Online Account Services.

MDU has no public API. Its customer portal (customer.montana-dakota.com) is an
Oracle CC&B self-service site: an AngularJS front end on a Spring backend. This
client signs in the same way the portal's own JavaScript does:

1. ``GET /login`` sets a session cookie; the page carries a CSRF token in
   ``<meta name="_csrf">`` (header name in ``<meta name="_csrf_header">``).
2. ``POST /login`` as a form with ``username``, ``password`` and ``_csrf``.
   Spring answers with a redirect: back to ``/login`` when the credentials are
   wrong, to a security-code page when MFA is on, otherwise into the portal.
3. MFA (5-digit code by email or text): ``GET mfa/contact-details``,
   ``POST mfa/initiate`` with the chosen contact, ``POST mfa/verify`` with the
   code and ``trust: true`` (0 means accepted), then ``GET /mfa/continue``.
   The ``mfa/...`` paths are relative to the security-code page.
4. ``GET /account/load-accounts-list`` lists the user's accounts and
   ``POST /account/load-account`` (body: the account ID) opens one.
5. ``GET /session/user`` returns the user with ``selectedAccount`` (balance,
   amount due, bills, service agreements in ``saList``).
6. ``POST /usage-history`` with ``{"saId", "premiseId"}`` returns monthly usage
   for one service agreement: ``usageYearComparisonChartList`` rows with
   ``month``, ``tyTherms`` (this year) and ``lyTherms`` (last year).

Endpoints and payloads were read from the portal's public bundles
(``/resources-built/ccbcust-login.min.js`` and ``ccbcust.min.js``). Response
fields the bundles don't pin down (date formats, the ``month`` label) are
parsed leniently.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from http.cookies import Morsel
import json
import logging
import re
from typing import Any
from urllib.parse import urljoin

import aiohttp
from yarl import URL

from .const import (
    DEFAULT_HOST,
    REQUEST_TIMEOUT,
    UNIT_DEKATHERM,
    UNIT_KWH,
    UNIT_THERM,
)
from .exceptions import (
    MDUAuthenticationError,
    MDUConnectionError,
    MDUMfaError,
    MDUMfaRequired,
    MDUSessionExpired,
)

_LOGGER = logging.getLogger(__name__)

_CSRF_RE = re.compile(
    r'<meta[^>]*name=["\']_csrf["\'][^>]*content=["\']([^"\']+)["\']'
    r'|<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']_csrf["\']',
    re.IGNORECASE,
)
_CSRF_HEADER_RE = re.compile(
    r'<meta[^>]*name=["\']_csrf_header["\'][^>]*content=["\']([^"\']+)["\']'
    r'|<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']_csrf_header["\']',
    re.IGNORECASE,
)
_MONTHS = {
    name: index
    for index, name in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}

# What mfa/verify answers, from the portal's MFA controller.
_MFA_VERIFY_ERRORS = {
    -1: ("Code submission failed", "cannot_connect"),
    -2: ("The security code has expired", "code_expired"),
    -3: ("No security code was requested", "code_expired"),
    3: ("Too many failed attempts", "too_many_attempts"),
}


@dataclass(frozen=True)
class ServiceAgreement:
    """One service (electric or gas) at one premise."""

    sa_id: str
    premise_id: str
    address: str | None = None
    status: str | None = None

    @property
    def key(self) -> str:
        return f"{self.sa_id}_{self.premise_id}"


@dataclass
class MDUAccount:
    """The parts of ``selectedAccount`` the integration uses."""

    account_id: str
    description: str | None = None
    status: str | None = None
    account_balance: float | None = None
    amount_due: float | None = None
    last_bill_amount: float | None = None
    last_bill_date: date | None = None
    due_date: date | None = None
    service_agreements: list[ServiceAgreement] = field(default_factory=list)


@dataclass(frozen=True)
class MonthlyUsage:
    """Usage billed in one month."""

    month: date  # first day of the month
    value: float


@dataclass
class UsageHistory:
    """Monthly usage for one service agreement."""

    service_agreement: ServiceAgreement
    sa_type: str | None
    gl_division: str | None
    unit: str
    months: list[MonthlyUsage]

    @property
    def is_gas(self) -> bool:
        return self.unit != UNIT_KWH

    @property
    def latest(self) -> MonthlyUsage | None:
        return self.months[-1] if self.months else None

    def value_for(self, month: date) -> float | None:
        return next((m.value for m in self.months if m.month == month), None)


class MDUClient:
    """Signs in to MDU Online Account Services and reads account data."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        host: str = DEFAULT_HOST,
    ) -> None:
        self._session = session
        self.username = username
        self._password = password
        self.base_url = f"https://{host}"
        self._csrf: str | None = None
        self._csrf_header = "X-CSRF-TOKEN"
        self._mfa_page: str | None = None
        self._mfa_contact: str | None = None
        self._account_id: str | None = None

    # ------------------------------------------------------------------
    # Sign-in
    # ------------------------------------------------------------------

    async def login(self) -> None:
        """Sign in. Raises MDUMfaRequired when a security code is needed."""
        self._csrf = None
        self._account_id = None
        url, html = await self._get_page("/login")
        self._read_csrf(html)
        if not self._csrf:
            raise MDUConnectionError("The sign-in page had no CSRF token")

        try:
            async with self._session.post(
                f"{self.base_url}/login",
                data={
                    "username": self.username,
                    "password": self._password,
                    "_csrf": self._csrf,
                },
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                html = await resp.text()
                final = resp.url
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise MDUConnectionError(f"Sign-in request failed: {err}") from err

        self._read_csrf(html)
        path = final.path.rstrip("/").lower()
        has_mfa_view = "MfaController" in html
        has_login_form = 'id="login-form"' in html or "LoginCtrl" in html
        _LOGGER.debug(
            "Sign-in landed on %s (code page: %s, sign-in form: %s)", final.path, has_mfa_view, has_login_form
        )

        # The portal may show the security-code page at /login itself, so the
        # address alone says little. Decide from what the session can do.
        if has_mfa_view or "mfa" in path:
            self._mfa_page = str(final)
            raise MDUMfaRequired("MDU asked for a security code")

        accounts = await self._probe_json("/account/load-accounts-list")
        if isinstance(accounts, dict) and accounts.get("object"):
            return

        mfa = await self._probe_json(urljoin(str(final), "mfa/enabled"))
        if isinstance(mfa, dict) and mfa.get("status") == "OK":
            self._mfa_page = str(final)
            raise MDUMfaRequired("MDU asked for a security code")

        if has_login_form or "error" in final.query:
            raise MDUAuthenticationError("MDU rejected the username or password")
        raise MDUConnectionError(f"Sign-in ended on an unexpected page: {final.path}")

    async def mfa_contacts(self) -> list[str]:
        """Return the email addresses and phone numbers a code can go to."""
        data = await self._mfa_call("GET", "mfa/contact-details")
        obj = (data or {}).get("object") or {}
        contacts = [str(c) for c in obj.get("emails") or []]
        contacts += [str(c) for c in obj.get("phones") or []]
        return contacts

    async def mfa_send_code(self, contact: str) -> None:
        """Ask MDU to send a security code to one of ``mfa_contacts()``."""
        data = await self._mfa_call("POST", "mfa/initiate", raw_body=contact)
        if not (isinstance(data, dict) and data.get("object")):
            raise MDUMfaError("MDU could not send a security code", "send_failed")
        self._mfa_contact = contact

    async def mfa_verify(self, code: str) -> None:
        """Submit the code, asking MDU to trust this client from now on."""
        code = code.strip()
        if not re.fullmatch(r"\d{5}", code):
            raise MDUMfaError("Security codes are 5 digits", "invalid_code")
        result = await self._mfa_call(
            "POST",
            "mfa/verify",
            json_body={
                "code": code,
                "contactDetails": [],
                "selectedValue": self._mfa_contact or "",
                "newEmail": "",
                "enabled": True,
                "checkedEnabled": True,
                "disableVerify": True,
                "trust": True,
            },
        )
        try:
            result = int(result)
        except (TypeError, ValueError) as err:
            raise MDUMfaError(f"Unexpected answer to the security code: {result!r}", "cannot_connect") from err
        if result != 0:
            message, reason = _MFA_VERIFY_ERRORS.get(result, ("Incorrect security code", "invalid_code"))
            raise MDUMfaError(message, reason)

        _, html = await self._get_page("/mfa/continue")
        self._read_csrf(html)
        self._mfa_page = None

    def export_trusted_cookies(self) -> dict[str, dict[str, Any]]:
        """Return the persistent cookies, so a trusted device stays trusted.

        After ``mfa_verify`` with ``trust`` the portal remembers this client by
        its ``mfa-token`` cookie. That one is always kept, with any other
        cookie that has an expiry; the session cookie is not worth storing.
        """
        cookies: dict[str, dict[str, Any]] = {}
        for cookie in self._session.cookie_jar:
            if not _is_trust_cookie(cookie):
                continue
            cookies[cookie.key] = {
                "value": cookie.value,
                "domain": cookie["domain"],
                "path": cookie["path"] or "/",
                "expires": cookie["expires"],
                "max-age": cookie["max-age"],
                "secure": bool(cookie["secure"]),
            }
        return cookies

    def import_trusted_cookies(self, cookies: dict[str, dict[str, Any]] | None) -> None:
        """Load cookies saved by ``export_trusted_cookies``."""
        for name, saved in (cookies or {}).items():
            morsel: Morsel = Morsel()
            morsel.set(name, saved["value"], saved["value"])
            morsel["domain"] = saved.get("domain") or ""
            morsel["path"] = saved.get("path") or "/"
            if saved.get("expires"):
                morsel["expires"] = saved["expires"]
            if saved.get("max-age"):
                morsel["max-age"] = saved["max-age"]
            if saved.get("secure"):
                morsel["secure"] = True
            self._session.cookie_jar.update_cookies({name: morsel}, URL(self.base_url))

    async def close(self) -> None:
        """Release this client's HTTP session.

        Home Assistant sessions are detached, never closed: closing would shut
        down the connector Home Assistant shares between integrations.
        """
        if not self._session.closed:
            self._session.detach()

    def clear_session(self) -> None:
        """Drop the session cookies, keeping the persistent (trusted) ones."""
        self._session.cookie_jar.clear(lambda c: not _is_trust_cookie(c))
        self._csrf = None
        self._account_id = None
        self._mfa_page = None

    async def logout(self) -> None:
        """End the portal session. Errors are ignored."""
        if not self._csrf:
            return
        try:
            async with self._session.post(
                f"{self.base_url}/logout",
                headers={self._csrf_header: self._csrf},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ):
                pass
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        self._csrf = None
        self._account_id = None

    # ------------------------------------------------------------------
    # Account data
    # ------------------------------------------------------------------

    async def get_accounts(self) -> dict[str, str]:
        """Return the user's accounts as ``{account_id: label}``."""
        data = await self._json("GET", "/account/load-accounts-list")
        user = (data or {}).get("object") or {}
        raw = user.get("userAccounts") or {}
        pairs = raw.items() if isinstance(raw, dict) else enumerate(raw)
        accounts: dict[str, str] = {}
        for key, item in pairs:
            if isinstance(item, dict):
                account_id = str(item.get("accountId") or item.get("id") or key)
                label = item.get("accountDescription") or item.get("description") or _address(
                    item.get("serviceAddress") or item.get("address")
                )
            else:
                account_id, label = str(key), str(item)
            accounts[account_id] = f"{account_id} – {label}" if label else account_id
        return accounts

    async def select_account(self, account_id: str) -> None:
        """Open an account; later calls read from it."""
        account_id = str(account_id)
        if self._account_id == account_id:
            return
        await self.get_accounts()  # the portal expects the list to be loaded first
        await self._request("POST", "/account/load-account", raw_body=account_id)
        # Opening an account leads to the payment center, which carries the
        # CSRF token the rest of the portal uses.
        _, html = await self._get_page("/payment-center")
        self._read_csrf(html)
        self._account_id = account_id

    async def get_account(self) -> MDUAccount:
        """Return the selected account."""
        data = await self._json("GET", "/session/user")
        if data is None:
            # Signed out, the portal answers 200 with an empty body.
            raise MDUSessionExpired("GET /session/user: not signed in")
        user = data.get("object", data) if isinstance(data, dict) else {}
        selected = user.get("selectedAccount") or {}
        if not selected:
            raise MDUConnectionError("The portal returned no selected account")
        return parse_account(selected)

    async def get_usage(self, agreement: ServiceAgreement, today: date | None = None) -> UsageHistory | None:
        """Return monthly usage for one service agreement, or None if it has none."""
        data = await self._json(
            "POST",
            "/usage-history",
            json_body={"saId": agreement.sa_id, "premiseId": agreement.premise_id},
        )
        if not isinstance(data, dict) or data.get("status") != "SUCCESS":
            _LOGGER.debug("No usage history for %s: %s", agreement.key, data)
            return None
        return parse_usage(agreement, data.get("object") or {}, today or date.today())

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _read_csrf(self, html: str) -> None:
        if match := _CSRF_RE.search(html or ""):
            self._csrf = match.group(1) or match.group(2)
        if match := _CSRF_HEADER_RE.search(html or ""):
            self._csrf_header = match.group(1) or match.group(2)

    async def _get_page(self, path: str) -> tuple[URL, str]:
        try:
            async with self._session.get(
                urljoin(self.base_url, path),
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status >= 400:
                    raise MDUConnectionError(f"GET {path} returned HTTP {resp.status}")
                return resp.url, await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise MDUConnectionError(f"GET {path} failed: {err}") from err

    async def _probe_json(self, path: str) -> Any:
        """GET without following redirects; return JSON, or None if not signed in."""
        headers = {"Accept": "application/json, text/plain, */*"}
        if self._csrf:
            headers[self._csrf_header] = self._csrf
        try:
            async with self._session.get(
                urljoin(self.base_url, path),
                headers=headers,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise MDUConnectionError(f"GET {path} failed: {err}") from err
        try:
            return json.loads(text) if text.strip() else None
        except ValueError:
            return None

    async def _mfa_call(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self._mfa_page:
            raise MDUMfaError("Sign in before asking for a security code", "cannot_connect")
        return await self._request(method, urljoin(self._mfa_page, path), parse_json=True, **kwargs)

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        return await self._request(method, path, parse_json=True, **kwargs)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        raw_body: str | None = None,
        parse_json: bool = False,
    ) -> Any:
        headers = {"Accept": "application/json, text/plain, */*"}
        if self._csrf:
            headers[self._csrf_header] = self._csrf
        kwargs: dict[str, Any] = {}
        if json_body is not None:
            kwargs["json"] = json_body
        elif raw_body is not None:
            # AngularJS sends a bare string body as-is, labelled as JSON.
            headers["Content-Type"] = "application/json;charset=UTF-8"
            kwargs["data"] = raw_body.encode()

        url = urljoin(self.base_url, path)
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                **kwargs,
            ) as resp:
                text = await resp.text()
                if resp.url.path.rstrip("/").lower() == "/login" or resp.status in (401, 403):
                    raise MDUSessionExpired(f"{method} {path}: not signed in")
                if resp.status >= 400:
                    raise MDUConnectionError(f"{method} {path} returned HTTP {resp.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise MDUConnectionError(f"{method} {path} failed: {err}") from err

        if not parse_json:
            return text
        try:
            return json.loads(text) if text.strip() else None
        except ValueError as err:
            # An HTML page instead of JSON means the session went away.
            if "<html" in text[:500].lower():
                raise MDUSessionExpired(f"{method} {path}: got a page instead of data") from err
            raise MDUConnectionError(f"{method} {path} returned invalid JSON") from err


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------


TRUST_COOKIE = "mfa-token"


def _is_trust_cookie(cookie: Morsel) -> bool:
    """Return whether a cookie should survive between sign-ins (``mfa-token`` or any persistent one)."""
    return cookie.key == TRUST_COOKIE or bool(cookie["expires"] or cookie["max-age"])


def usage_unit(gl_division: str | None, sa_type: str | None) -> str:
    """Return the unit MDU reports usage in, as the portal's chart decides it.

    Montana-Dakota (MDU) and Great Plains (GPG) report gas in dekatherms and
    MDU electric in kWh; other divisions report gas in therms.
    """
    division = (gl_division or "").upper()
    is_gas = "gas" in (sa_type or "").lower()
    if division == "MDU" and not is_gas:
        return UNIT_KWH
    if division in ("MDU", "GPG"):
        return UNIT_DEKATHERM
    return UNIT_THERM


def parse_account(selected: dict[str, Any]) -> MDUAccount:
    """Build an MDUAccount from the portal's ``selectedAccount``."""
    bills = [b for b in selected.get("bills") or [] if isinstance(b, dict)]
    bills.sort(key=lambda b: parse_date(b.get("billDate")) or date.min)
    latest = bills[-1] if bills else {}

    agreements = []
    for sa in selected.get("saList") or []:
        if not isinstance(sa, dict) or sa.get("id") in (None, ""):
            continue
        premise = sa.get("premise") or {}
        agreements.append(
            ServiceAgreement(
                sa_id=str(sa["id"]),
                premise_id=str(premise.get("id") or ""),
                address=_address(premise.get("address")),
                status=sa.get("status"),
            )
        )

    return MDUAccount(
        account_id=str(selected.get("accountId") or ""),
        description=selected.get("accountDescription"),
        status=selected.get("status") or selected.get("genericStatus"),
        account_balance=parse_money(selected.get("accountBalance")),
        amount_due=parse_money(selected.get("amountDue")),
        last_bill_amount=parse_money(selected.get("lastBillAmountDue")),
        last_bill_date=parse_date(latest.get("billDate")),
        due_date=parse_date(latest.get("dueDate")),
        service_agreements=agreements,
    )


def parse_usage(agreement: ServiceAgreement, obj: dict[str, Any], today: date) -> UsageHistory:
    """Build a UsageHistory from a ``/usage-history`` response object.

    Each chart row holds one calendar month with this year's (``tyTherms``)
    and last year's (``lyTherms``) usage, whatever the unit.
    """
    gl_division = obj.get("glDivision")
    sa_type = obj.get("saType")

    rows: list[tuple[int, int | None, float | None, float | None]] = []
    for row in obj.get("usageYearComparisonChartList") or []:
        if not isinstance(row, dict):
            continue
        parsed = parse_month_label(row.get("month"))
        if parsed is None:
            continue
        month, year = parsed
        rows.append((month, year, parse_number(row.get("tyTherms")), parse_number(row.get("lyTherms"))))

    # Rows without a year: if "this year" has figures for months later than
    # the current one, the chart is a rolling 12 months (those months are
    # last year's); otherwise it is the calendar year with the future empty.
    rolling = any(
        year is None and month > today.month and (ty or 0) > 0 for month, year, ty, _ in rows
    )

    values: dict[date, float] = {}
    for month, year, ty, ly in rows:
        if year is None:
            year = today.year - 1 if rolling and month > today.month else today.year
        this_year = date(year, month, 1)
        last_year = date(year - 1, month, 1)
        # Last year's figure first, so this year's wins on any overlap.
        for start, value in ((last_year, ly), (this_year, ty)):
            if value is None or start > today:
                continue
            values[start] = value

    # The current month reads 0 until it is billed; drop trailing zeros.
    months = [MonthlyUsage(m, values[m]) for m in sorted(values)]
    while months and months[-1].value == 0:
        months.pop()

    return UsageHistory(
        service_agreement=agreement,
        sa_type=sa_type,
        gl_division=gl_division,
        unit=usage_unit(gl_division, sa_type),
        months=months,
    )


def parse_month_label(label: Any) -> tuple[int, int | None] | None:
    """Parse the chart's month label into (month, year or None).

    Accepts "Jan-2026", "Jan-26", "January 2026", "01-2026", "2026-01" and "Jan".
    """
    if label is None:
        return None
    parts = [p for p in re.split(r"[-/\s]+", str(label).strip()) if p]
    month = year = None
    for part in parts:
        low = part.lower()
        if low[:3] in _MONTHS and month is None:
            month = _MONTHS[low[:3]]
        elif part.isdigit() and len(part) == 4:
            year = int(part)
        elif part.isdigit() and month is None and 1 <= int(part) <= 12:
            month = int(part)
        elif part.isdigit() and len(part) == 2:
            year = 2000 + int(part)
    if month is None:
        return None
    return month, year


def parse_date(value: Any) -> date | None:
    """Parse the date formats the portal is likely to use."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        # Java epoch milliseconds
        seconds = value / 1000 if value > 10**11 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc).date()
    text = str(value).strip()
    if text.isdigit():
        return parse_date(int(text))
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        _LOGGER.debug("Could not parse date %r", value)
        return None


def parse_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def parse_money(value: Any) -> float | None:
    if isinstance(value, str):
        text = value.replace("$", "").replace(",", "").strip()
        if text.endswith("CR"):  # credit balance
            text = "-" + text[:-2].strip()
        if text.startswith("(") and text.endswith(")"):
            text = "-" + text[1:-1]
        return parse_number(text)
    return parse_number(value)


def _address(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("formattedAddress", "address", "fullAddress", "displayAddress"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
        parts = [
            value.get(k)
            for k in ("address1", "addressLine1", "street", "city", "state", "postal", "zip")
            if value.get(k)
        ]
        return ", ".join(str(p) for p in parts) or None
    return str(value)
