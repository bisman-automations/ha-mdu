# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
