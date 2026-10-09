"""Tests for the MDU portal client against a mocked portal."""
import json
import re

import aiohttp
from aioresponses import CallbackResult, aioresponses
import pytest

from custom_components.mdu.api import MDUClient
from custom_components.mdu.exceptions import (
    MDUAuthenticationError,
    MDUConnectionError,
    MDUMfaError,
    MDUMfaRequired,
    MDUSessionExpired,
)

from .conftest import load_fixture

BASE = "https://customer.montana-dakota.com"


@pytest.fixture
async def client():
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(quote_cookie=False))
    yield MDUClient(session, "donavan", "hunter2")
    await session.close()


def _login_page(mocked: aioresponses) -> None:
    mocked.get(f"{BASE}/login", body=load_fixture("login.html"), content_type="text/html")


def _not_signed_in(mocked: aioresponses) -> None:
    """Protected endpoints redirect to the sign-in page."""
    for path in ("/account/load-accounts-list", "/mfa/enabled"):
        mocked.get(f"{BASE}{path}", status=302, headers={"Location": f"{BASE}/login"})


async def test_login_success_and_read_account(client: MDUClient) -> None:
    posted = {}

    def capture_login(url, **kwargs):
        posted.update(kwargs["data"])
        return CallbackResult(status=302, headers={"Location": f"{BASE}/account/load"})

    with aioresponses() as mocked:
        _login_page(mocked)
        mocked.post(f"{BASE}/login", callback=capture_login)
        mocked.get(f"{BASE}/account/load", body=load_fixture("app_page.html"), content_type="text/html")
        mocked.get(f"{BASE}/account/load-accounts-list", payload=load_fixture("accounts_list.json"), repeat=True)
        mocked.post(f"{BASE}/account/load-account", status=200, body="")
        mocked.get(f"{BASE}/payment-center", body=load_fixture("app_page.html"), content_type="text/html")
        mocked.get(f"{BASE}/session/user", payload=load_fixture("session_user.json"))
        mocked.post(f"{BASE}/usage-history", payload=load_fixture("usage_electric.json"))

        await client.login()
        assert posted == {"username": "donavan", "password": "hunter2", "_csrf": "csrf-login-token"}

        assert await client.get_accounts() == {"1234567890": "1234567890 – Home"}
        await client.select_account("1234567890")
        account = await client.get_account()
        assert account.amount_due == 48.75

        history = await client.get_usage(account.service_agreements[0])
        assert history is not None and history.unit == "kWh"

        # Account selection posts the bare account ID with the app's CSRF token.
        load = mocked.requests[("POST", aiohttp.client.URL(f"{BASE}/account/load-account"))][0]
        assert load.kwargs["data"] == b"1234567890"
        assert load.kwargs["headers"]["X-CSRF-TOKEN"] == "csrf-app-token"
        usage = mocked.requests[("POST", aiohttp.client.URL(f"{BASE}/usage-history"))][0]
        assert usage.kwargs["json"] == {"saId": "5550001", "premiseId": "7770001"}
        assert usage.kwargs["headers"]["X-CSRF-TOKEN"] == "csrf-app-token"


async def test_login_bad_password(client: MDUClient) -> None:
    with aioresponses() as mocked:
        _login_page(mocked)
        mocked.post(f"{BASE}/login", status=302, headers={"Location": f"{BASE}/login?error"})
        mocked.get(re.compile(r".*/login\?error$"), body=load_fixture("login.html"), content_type="text/html")
        _not_signed_in(mocked)
        with pytest.raises(MDUAuthenticationError):
            await client.login()


async def test_login_mfa_flow(client: MDUClient) -> None:
    verify_body = {}

    def capture_verify(url, **kwargs):
        verify_body.update(kwargs["json"])
        return CallbackResult(body="0", content_type="application/json")

    with aioresponses() as mocked:
        _login_page(mocked)
        mocked.post(f"{BASE}/login", status=302, headers={"Location": f"{BASE}/mfa"})
        mocked.get(f"{BASE}/mfa", body=load_fixture("login.html"), content_type="text/html")
        mocked.get(
            f"{BASE}/mfa/contact-details",
            payload={"status": "OK", "object": {"emails": ["d@example.com"], "phones": ["7015551234"]}},
        )
        mocked.post(f"{BASE}/mfa/initiate", payload={"status": "OK", "object": True})
        mocked.post(f"{BASE}/mfa/verify", callback=capture_verify)
        mocked.get(
            f"{BASE}/mfa/continue",
            body=load_fixture("app_page.html"),
            content_type="text/html",
        )

        with pytest.raises(MDUMfaRequired):
            await client.login()
        assert await client.mfa_contacts() == ["d@example.com", "7015551234"]
        await client.mfa_send_code("7015551234")
        with pytest.raises(MDUMfaError):
            await client.mfa_verify("1234")  # not 5 digits
        await client.mfa_verify("12345")

    assert verify_body["code"] == "12345"
    assert verify_body["trust"] is True
    assert verify_body["selectedValue"] == "7015551234"


@pytest.mark.parametrize(("answer", "reason"), [(1, "invalid_code"), (-2, "code_expired"), (3, "too_many_attempts")])
async def test_mfa_verify_rejected(client: MDUClient, answer: int, reason: str) -> None:
    with aioresponses() as mocked:
        _login_page(mocked)
        mocked.post(f"{BASE}/login", status=302, headers={"Location": f"{BASE}/mfa"})
        mocked.get(f"{BASE}/mfa", body=load_fixture("login.html"), content_type="text/html")
        mocked.post(f"{BASE}/mfa/verify", body=json.dumps(answer), content_type="application/json")
        with pytest.raises(MDUMfaRequired):
            await client.login()
        with pytest.raises(MDUMfaError) as err:
            await client.mfa_verify("12345")
    assert err.value.reason == reason


async def test_session_expired_is_detected(client: MDUClient) -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/session/user", status=302, headers={"Location": f"{BASE}/login"})
        mocked.get(f"{BASE}/login", body=load_fixture("login.html"), content_type="text/html")
        with pytest.raises(MDUSessionExpired):
            await client.get_account()


async def test_trusted_cookies_round_trip(client: MDUClient) -> None:
    client.import_trusted_cookies(
        {"TRUSTED_DEVICE": {"value": "abc123", "domain": "", "path": "/", "max-age": "7776000", "secure": True}}
    )
    assert client.export_trusted_cookies()["TRUSTED_DEVICE"]["value"] == "abc123"
    client.clear_session()
    assert "TRUSTED_DEVICE" in client.export_trusted_cookies()
    assert re.match(r"https://", client.base_url)


async def test_mfa_page_served_at_login(client: MDUClient) -> None:
    """The portal can show the code page at /login itself; that is not a bad password."""
    with aioresponses() as mocked:
        _login_page(mocked)
        mocked.post(f"{BASE}/login", body=load_fixture("mfa_page.html"), content_type="text/html")
        mocked.get(f"{BASE}/mfa/contact-details", payload={"status": "OK", "object": {"emails": ["d@x.com"], "phones": []}})
        with pytest.raises(MDUMfaRequired):
            await client.login()
        assert await client.mfa_contacts() == ["d@x.com"]


async def test_mfa_detected_by_endpoint(client: MDUClient) -> None:
    """No code page markup, but the MFA endpoint answers: a code is needed."""
    with aioresponses() as mocked:
        _login_page(mocked)
        mocked.post(f"{BASE}/login", body="<html><body>Loading…</body></html>", content_type="text/html")
        mocked.get(f"{BASE}/account/load-accounts-list", status=302, headers={"Location": f"{BASE}/login"})
        mocked.get(f"{BASE}/mfa/enabled", payload={"status": "OK", "object": True})
        with pytest.raises(MDUMfaRequired):
            await client.login()


async def test_login_success_detected_by_accounts(client: MDUClient) -> None:
    """Landing on /login is fine if the account list loads."""
    with aioresponses() as mocked:
        _login_page(mocked)
        mocked.post(f"{BASE}/login", body=load_fixture("login.html"), content_type="text/html")
        mocked.get(f"{BASE}/account/load-accounts-list", payload=load_fixture("accounts_list.json"))
        await client.login()


async def test_unexpected_page_is_not_bad_password(client: MDUClient) -> None:
    with aioresponses() as mocked:
        _login_page(mocked)
        mocked.post(f"{BASE}/login", body="<html><body>Maintenance</body></html>", content_type="text/html")
        mocked.get(f"{BASE}/", body="<html><body>Maintenance</body></html>", content_type="text/html")
        for path in ("/account/load-accounts-list", "/mfa/enabled"):
            mocked.get(f"{BASE}{path}", status=302, headers={"Location": f"{BASE}/login"}, repeat=True)
        with pytest.raises(MDUConnectionError) as err:
            await client.login()
    assert "Maintenance" in str(err.value)


def _empty_answer(mocked: aioresponses, **headers: str) -> None:
    """The sign-in post answers 200 with an empty body."""
    mocked.post(f"{BASE}/login", status=200, body="", headers=headers)


async def test_empty_answer_with_refresh_leads_to_code_page(client: MDUClient) -> None:
    with aioresponses() as mocked:
        _login_page(mocked)
        _empty_answer(mocked, Refresh="0; url=/mfa")
        mocked.get(f"{BASE}/account/load-accounts-list", status=302, headers={"Location": f"{BASE}/login"})
        mocked.get(f"{BASE}/mfa/enabled", status=302, headers={"Location": f"{BASE}/login"})
        mocked.get(f"{BASE}/mfa", body=load_fixture("mfa_page.html"), content_type="text/html")
        with pytest.raises(MDUMfaRequired):
            await client.login()


async def test_empty_answer_then_signed_in(client: MDUClient) -> None:
    with aioresponses() as mocked:
        _login_page(mocked)
        _empty_answer(mocked)
        mocked.get(f"{BASE}/account/load-accounts-list", status=302, headers={"Location": f"{BASE}/login"})
        mocked.get(f"{BASE}/mfa/enabled", status=302, headers={"Location": f"{BASE}/login"})
        mocked.get(f"{BASE}/", status=302, headers={"Location": f"{BASE}/payment-center"})
        mocked.get(f"{BASE}/payment-center", body=load_fixture("app_page.html"), content_type="text/html")
        mocked.get(f"{BASE}/account/load-accounts-list", payload=load_fixture("accounts_list.json"))
        await client.login()


async def test_empty_answer_then_sign_in_form_is_bad_password(client: MDUClient) -> None:
    with aioresponses() as mocked:
        _login_page(mocked)
        _empty_answer(mocked)
        for path in ("/account/load-accounts-list", "/mfa/enabled"):
            mocked.get(f"{BASE}{path}", status=302, headers={"Location": f"{BASE}/login"}, repeat=True)
        mocked.get(f"{BASE}/", status=302, headers={"Location": f"{BASE}/login"})
        mocked.get(f"{BASE}/login", body=load_fixture("login.html"), content_type="text/html")
        with pytest.raises(MDUAuthenticationError):
            await client.login()


def test_summarize_headers_hides_cookie_values() -> None:
    from custom_components.mdu.api import summarize_headers

    summary = summarize_headers({"Set-Cookie": "JSESSIONID=secret; Path=/", "Content-Length": "0", "X-Thing": "v"})
    assert summary == "set-cookie JSESSIONID, content-length=0, x-thing"
    assert "secret" not in summary


async def test_empty_session_user_means_signed_out(client: MDUClient) -> None:
    with aioresponses() as mocked:
        mocked.get(f"{BASE}/session/user", body="", status=200)
        with pytest.raises(MDUSessionExpired):
            await client.get_account()


async def test_mfa_token_kept_without_expiry(client: MDUClient) -> None:
    client.import_trusted_cookies({"mfa-token": {"value": "tok", "domain": "", "path": "/"}})
    client.clear_session()
    assert client.export_trusted_cookies()["mfa-token"]["value"] == "tok"


def test_describe_page() -> None:
    from custom_components.mdu.api import describe_page

    html = "<html><head><title>Request Rejected</title><script>var x=1;</script></head><body><h1>The requested URL was rejected.</h1><p>{{ strings.x }}</p></body></html>"
    assert describe_page(html) == '"Request Rejected" The requested URL was rejected.'
    assert describe_page("") == "(no text, 0 bytes)"


async def test_create_client_does_not_quote_cookies(hass) -> None:
    """Base64 session cookies must go back exactly as the portal set them."""
    from http.cookies import SimpleCookie

    from custom_components.mdu import create_client

    client = create_client(hass, {"username": "u", "password": "p"}, auto_cleanup=False)
    url = aiohttp.client.URL(BASE)
    client._session.cookie_jar.update_cookies(SimpleCookie("SESSION=YmFkZjAwZA==; Path=/"), url)
    assert client._session.cookie_jar.filter_cookies(url)["SESSION"].coded_value == "YmFkZjAwZA=="
    await client.close()


def test_address_parts_are_trimmed() -> None:
    from custom_components.mdu.api import _address

    assert _address({"street": "123 MAIN ST      ", "city": "BISMARCK  ", "state": "ND"}) == "123 MAIN ST, BISMARCK, ND"
