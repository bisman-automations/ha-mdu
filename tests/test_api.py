"""Tests for the MDU portal client against a fake portal served over real HTTP."""

import re

import aiohttp
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
from .portal import SESSION_COOKIE, FakePortal, as_json, empty, html, redirect

BASE = "https://customer.montana-dakota.com"


@pytest.fixture
async def portal(socket_enabled):
    """The fake portal listens on 127.0.0.1, so these tests need local sockets."""
    portal = FakePortal()
    await portal.start()
    yield portal
    await portal.close()


@pytest.fixture
async def client(portal: FakePortal):
    # unsafe=True only because the test server is on 127.0.0.1; aiohttp's jar
    # ignores cookies from IP addresses otherwise. quote_cookie=False matches
    # the integration's own session (see create_client).
    session = aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(unsafe=True, quote_cookie=False)
    )
    client = MDUClient(session, "donavan", "hunter2")
    client.base_url = portal.url
    yield client
    await session.close()


def _login_page(portal: FakePortal) -> None:
    portal.on("GET", "/login", html(load_fixture("login.html")))


def _not_signed_in(portal: FakePortal) -> None:
    """Protected endpoints redirect to the sign-in page."""
    for path in ("/account/load-accounts-list", "/mfa/enabled"):
        portal.on("GET", path, redirect("/login"))


async def test_login_success_and_read_account(
    portal: FakePortal, client: MDUClient
) -> None:
    _login_page(portal)
    portal.on("POST", "/login", redirect("/account/load"))
    portal.on("GET", "/account/load", html(load_fixture("app_page.html")))
    portal.on(
        "GET",
        "/account/load-accounts-list",
        as_json(load_fixture("accounts_list.json")),
    )
    portal.on("POST", "/account/load-account", empty())
    portal.on("GET", "/payment-center", html(load_fixture("app_page.html")))
    portal.on("GET", "/session/user", as_json(load_fixture("session_user.json")))
    portal.on("POST", "/usage-history", as_json(load_fixture("usage_electric.json")))

    await client.login()
    login = portal.sent("POST", "/login")[0]
    assert login.form == {
        "username": "donavan",
        "password": "hunter2",
        "_csrf": "csrf-login-token",
    }
    # The session cookie goes back exactly as set, not wrapped in quotes.
    assert f"{SESSION_COOKIE[0]}={SESSION_COOKIE[1]}" in login.headers["Cookie"]
    assert login.headers["X-CSRF-TOKEN"] == "csrf-login-token"

    assert await client.get_accounts() == {"1234567890": "1234567890 – Home"}
    await client.select_account("1234567890")
    account = await client.get_account()
    assert account.amount_due == 48.75

    history = await client.get_usage(account.service_agreements[0])
    assert history is not None and history.unit == "kWh"

    # Account selection posts the bare account ID; later calls carry the app's CSRF token.
    load = portal.sent("POST", "/account/load-account")[0]
    assert load.body == b"1234567890"
    usage = portal.sent("POST", "/usage-history")[0]
    assert usage.json == {"saId": "5550001", "premiseId": "7770001"}
    assert usage.headers["X-CSRF-TOKEN"] == "csrf-app-token"


async def test_login_bad_password(portal: FakePortal, client: MDUClient) -> None:
    _login_page(portal)
    portal.on("POST", "/login", redirect("/login?error"))
    _not_signed_in(portal)
    with pytest.raises(MDUAuthenticationError):
        await client.login()


async def test_login_mfa_flow(portal: FakePortal, client: MDUClient) -> None:
    _login_page(portal)
    portal.on("POST", "/login", redirect("/mfa"))
    portal.on("GET", "/mfa", html(load_fixture("mfa_page.html")))
    portal.on(
        "GET",
        "/mfa/contact-details",
        as_json(
            {
                "status": "OK",
                "object": {"emails": ["d@example.com"], "phones": ["7015551234"]},
            }
        ),
    )
    portal.on("POST", "/mfa/initiate", as_json({"status": "OK", "object": True}))
    portal.on("POST", "/mfa/verify", as_json(0))
    portal.on("GET", "/mfa/continue", html(load_fixture("app_page.html")))

    with pytest.raises(MDUMfaRequired):
        await client.login()
    assert await client.mfa_contacts() == ["d@example.com", "7015551234"]
    await client.mfa_send_code("7015551234")
    assert portal.sent("POST", "/mfa/initiate")[0].body == b"7015551234"
    with pytest.raises(MDUMfaError):
        await client.mfa_verify("1234")  # not 5 digits
    await client.mfa_verify("12345")

    verify = portal.sent("POST", "/mfa/verify")[0].json
    assert verify["code"] == "12345"
    assert verify["trust"] is True
    assert verify["selectedValue"] == "7015551234"
    assert portal.sent("GET", "/mfa/continue")


@pytest.mark.parametrize(
    ("answer", "reason"),
    [(1, "invalid_code"), (-2, "code_expired"), (3, "too_many_attempts")],
)
async def test_mfa_verify_rejected(
    portal: FakePortal, client: MDUClient, answer: int, reason: str
) -> None:
    _login_page(portal)
    portal.on("POST", "/login", redirect("/mfa"))
    portal.on("GET", "/mfa", html(load_fixture("mfa_page.html")))
    portal.on("POST", "/mfa/verify", as_json(answer))
    with pytest.raises(MDUMfaRequired):
        await client.login()
    with pytest.raises(MDUMfaError) as err:
        await client.mfa_verify("12345")
    assert err.value.reason == reason


async def test_session_expired_is_detected(
    portal: FakePortal, client: MDUClient
) -> None:
    portal.on("GET", "/session/user", redirect("/login"))
    _login_page(portal)
    with pytest.raises(MDUSessionExpired):
        await client.get_account()


async def test_empty_session_user_means_signed_out(
    portal: FakePortal, client: MDUClient
) -> None:
    portal.on("GET", "/session/user", empty())
    with pytest.raises(MDUSessionExpired):
        await client.get_account()


async def test_mfa_page_served_at_login(portal: FakePortal, client: MDUClient) -> None:
    """A code page answered at /login itself is not a bad password."""
    _login_page(portal)
    portal.on("POST", "/login", html(load_fixture("mfa_page.html")))
    portal.on(
        "GET",
        "/mfa/contact-details",
        as_json({"status": "OK", "object": {"emails": ["d@x.com"], "phones": []}}),
    )
    with pytest.raises(MDUMfaRequired):
        await client.login()
    assert await client.mfa_contacts() == ["d@x.com"]


async def test_mfa_detected_by_endpoint(portal: FakePortal, client: MDUClient) -> None:
    """No code page markup, but the MFA endpoint answers: a code is needed."""
    _login_page(portal)
    portal.on("POST", "/login", html("<html><body>Loading…</body></html>"))
    portal.on("GET", "/account/load-accounts-list", redirect("/login"))
    portal.on("GET", "/mfa/enabled", as_json({"status": "OK", "object": True}))
    with pytest.raises(MDUMfaRequired):
        await client.login()


async def test_login_success_detected_by_accounts(
    portal: FakePortal, client: MDUClient
) -> None:
    """Landing on /login is fine if the account list loads."""
    _login_page(portal)
    portal.on("POST", "/login", html(load_fixture("login.html")))
    portal.on(
        "GET",
        "/account/load-accounts-list",
        as_json(load_fixture("accounts_list.json")),
    )
    await client.login()


async def test_unexpected_page_is_not_bad_password(
    portal: FakePortal, client: MDUClient
) -> None:
    _login_page(portal)
    portal.on("POST", "/login", html("<html><body>Maintenance</body></html>"))
    portal.on("GET", "/", html("<html><body>Maintenance</body></html>"))
    _not_signed_in(portal)
    with pytest.raises(MDUConnectionError) as err:
        await client.login()
    assert "Maintenance" in str(err.value)


async def test_empty_answer_with_refresh_leads_to_code_page(
    portal: FakePortal, client: MDUClient
) -> None:
    _login_page(portal)
    portal.on("POST", "/login", empty(Refresh="0; url=/mfa"))
    _not_signed_in(portal)
    portal.on("GET", "/mfa", html(load_fixture("mfa_page.html")))
    with pytest.raises(MDUMfaRequired):
        await client.login()


async def test_empty_answer_then_signed_in(
    portal: FakePortal, client: MDUClient
) -> None:
    _login_page(portal)
    portal.on("POST", "/login", empty())
    portal.on("GET", "/mfa/enabled", redirect("/login"))
    # Not signed in when first probed; signed in once the next page has loaded.
    portal.on(
        "GET",
        "/account/load-accounts-list",
        redirect("/login"),
        as_json(load_fixture("accounts_list.json")),
    )
    portal.on("GET", "/", redirect("/payment-center"))
    portal.on("GET", "/payment-center", html(load_fixture("app_page.html")))
    await client.login()


async def test_empty_answer_then_sign_in_form_is_bad_password(
    portal: FakePortal, client: MDUClient
) -> None:
    _login_page(portal)
    portal.on("POST", "/login", empty())
    _not_signed_in(portal)
    portal.on("GET", "/", redirect("/login"))
    with pytest.raises(MDUAuthenticationError):
        await client.login()


async def test_trusted_cookies_round_trip(client: MDUClient) -> None:
    client.import_trusted_cookies(
        {
            "TRUSTED_DEVICE": {
                "value": "abc123",
                "domain": "",
                "path": "/",
                "max-age": "7776000",
                "secure": False,
            }
        }
    )
    assert client.export_trusted_cookies()["TRUSTED_DEVICE"]["value"] == "abc123"
    client.clear_session()
    assert "TRUSTED_DEVICE" in client.export_trusted_cookies()


async def test_mfa_token_kept_without_expiry(client: MDUClient) -> None:
    client.import_trusted_cookies(
        {"mfa-token": {"value": "tok", "domain": "", "path": "/"}}
    )
    client.clear_session()
    assert client.export_trusted_cookies()["mfa-token"]["value"] == "tok"


async def test_trusted_cookie_is_sent_on_sign_in(
    portal: FakePortal, client: MDUClient
) -> None:
    """A saved trust cookie goes out with the sign-in, so MDU can skip the code."""
    client.import_trusted_cookies(
        {"mfa-token": {"value": "tok|123-abc", "domain": "", "path": "/"}}
    )
    _login_page(portal)
    portal.on("POST", "/login", redirect("/account/load"))
    portal.on("GET", "/account/load", html(load_fixture("app_page.html")))
    portal.on(
        "GET",
        "/account/load-accounts-list",
        as_json(load_fixture("accounts_list.json")),
    )
    await client.login()
    assert "mfa-token=tok|123-abc" in portal.sent("POST", "/login")[0].headers["Cookie"]


def test_summarize_headers_hides_cookie_values() -> None:
    from custom_components.mdu.api import summarize_headers

    summary = summarize_headers(
        {
            "Set-Cookie": "JSESSIONID=secret; Path=/",
            "Content-Length": "0",
            "X-Thing": "v",
        }
    )
    assert summary == "set-cookie JSESSIONID, content-length=0, x-thing"
    assert "secret" not in summary


def test_describe_page() -> None:
    from custom_components.mdu.api import describe_page

    html_page = (
        "<html><head><title>Request Rejected</title><script>var x=1;</script></head>"
        "<body><h1>The requested URL was rejected.</h1><p>{{ strings.x }}</p></body></html>"
    )
    assert (
        describe_page(html_page) == '"Request Rejected" The requested URL was rejected.'
    )
    assert describe_page("") == "(no text, 0 bytes)"


async def test_create_client_does_not_quote_cookies(hass) -> None:
    """Base64 session cookies must go back exactly as the portal set them."""
    from http.cookies import SimpleCookie

    from custom_components.mdu import create_client

    client = create_client(hass, {"username": "u", "password": "p"}, auto_cleanup=False)
    assert re.match(r"https://", client.base_url)
    url = aiohttp.client.URL(BASE)
    client._session.cookie_jar.update_cookies(
        SimpleCookie("SESSION=YmFkZjAwZA==; Path=/"), url
    )
    assert (
        client._session.cookie_jar.filter_cookies(url)["SESSION"].coded_value
        == "YmFkZjAwZA=="
    )
    await client.close()


def test_address_parts_are_trimmed() -> None:
    from custom_components.mdu.api import _address

    assert (
        _address({"street": "123 MAIN ST      ", "city": "BISMARCK  ", "state": "ND"})
        == "123 MAIN ST, BISMARCK, ND"
    )
