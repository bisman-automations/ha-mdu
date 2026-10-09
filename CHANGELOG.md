# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
- Signing in with MFA turned on reported "MDU rejected the username or
  password". The portal shows the security-code page at the sign-in address,
  so sign-in is now judged by what the session can do (load the account list,
  or answer the MFA check) instead of by the address it lands on. A page the
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
