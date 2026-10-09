# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.5] - 2026-10-09

### Fixed
- Sign-in failed for everyone ("MDU rejected the username or password", or
  an empty page in the logs). aiohttp wraps cookie values containing `=` in
  quotes when sending them back, so the portal didn't recognize its own
  session cookie and dropped the sign-in. Cookies are now sent exactly as the
  portal set them.
- The sign-in form also carries its security token as a header, the way the
  portal's own pages send it.
- Service addresses no longer include the portal's trailing padding.

## [0.1.4] - 2026-10-09

### Fixed
- The portal can answer the sign-in form with an empty page. The integration
  now does what a browser would: follows a `Refresh` or `Location` header if
  there is one, otherwise loads the next page, and decides from there whether
  sign-in worked, needs a security code, or was refused.

### Changed
- If sign-in still can't be understood, the log includes the response
  headers (cookie names only, never values) and the follow-up page.

## [0.1.3] - 2026-10-09

### Changed
- The sign-in form is posted with the `Origin` and `Referer` headers a browser
  sends, in case the portal or its firewall refuses posts without them.
- When sign-in ends on a page the integration doesn't recognise, the log says
  the HTTP status, the redirects taken, and the page's title and opening text.

## [0.1.2] - 2026-10-09

### Fixed
- The integration closed its Home Assistant HTTP session, which also shut
  down the connection pool Home Assistant shares between integrations. Later
  sign-in attempts then failed with "Couldn't reach MDU" until a restart.
  Sessions are now detached, as Home Assistant requires.

### Changed
- Sign-in problems during setup are logged as warnings with the reason, so
  they show in Home Assistant's logs without debug logging.

## [0.1.1] - 2026-10-09

### Fixed
- Sign-in is judged by what the session can do (load the account list, or
  answer the MFA check) instead of only by the address it lands on. A page the
  integration doesn't recognize is reported as a connection problem, not a
  wrong password.
- The portal's trusted-device cookie (`mfa-token`) is always kept, so a
  verified connection isn't asked for a code again.

## [0.1.0] - 2026-10-09

### Added
- First release. Signs in to MDU Online Account Services, with support for
  security codes by email or text (the connection is then trusted, so codes
  aren't asked for again).
- Account sensors: account balance, amount due, last bill amount, due date and
  last bill date.
- Usage sensors for each electric (kWh) and gas (GJ, converted from
  dekatherms) service, showing the most recent billed month.
- Monthly long-term statistics for each service, for the Energy dashboard.
- Reauthentication when the password changes or MDU asks for a new code.
