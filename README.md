<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/dark_logo.png">
    <img src="assets/logo.png" alt="Montana-Dakota Utilities for Home Assistant" width="448">
  </picture>
</p>

# Montana-Dakota Utilities for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/github/v/release/bisman-automations/ha-mdu)](https://github.com/bisman-automations/ha-mdu/releases)
[![License](https://img.shields.io/github/license/bisman-automations/ha-mdu)](LICENSE)

A Home Assistant custom integration for [Montana-Dakota Utilities](https://www.montana-dakota.com/) (MDU) customers. It signs in to MDU Online Account Services and brings your monthly electric and gas usage, balance and bill dates into Home Assistant, including the Energy dashboard.

> This is an unofficial integration. MDU has no public API or Green Button export, so it reads the same pages the customer portal does. If MDU changes its portal, the integration may need an update.

## What you get

**Account sensors** (one device per account)

| Sensor | Description |
| --- | --- |
| Account balance | What's owed on the account right now ($0 when paid up) |
| Amount due | Amount due on the most recent bill |
| Last bill amount | Total of the most recent bill |
| Due date | Due date of the most recent bill |
| Last bill date | Date of the most recent bill |
| Last payment amount | Most recent completed payment |
| Last payment date | Date of that payment |
| Autopay | On when the account is enrolled in Autopay (diagnostic) |
| Budget Pay | On when the account is on Budget Pay (diagnostic) |

**Usage sensors** (one per active electric or gas service)

| Sensor | Unit | Description |
| --- | --- | --- |
| Electric usage last month | kWh | Usage on the most recent bill |
| Gas usage last month | GJ | Usage on the most recent bill, converted from dekatherms |

Each usage sensor's attributes include the billing month, the value in MDU's own unit (`source_value`, `source_unit`), the same month last year, and the service address. Closed services (an old address, for example) are skipped.

**Long-term statistics for the Energy dashboard**

| Statistic | Unit | Where to add it |
| --- | --- | --- |
| `mdu:<account>_<service>_electric_usage` | kWh | **Electricity grid → Grid consumption** |
| `mdu:<account>_<service>_gas_usage` | GJ | **Gas consumption** |
| `mdu:<account>_bill_cost` | USD | As the cost of that consumption: choose **Use an entity tracking the total costs** and pick this statistic |

Usage covers every billed month MDU shows (about two years), one entry per month. The cost statistic is each bill's total, by the month it was billed. Bills cover the whole account, so for an account with both electric and gas service the cost is their combined total.

### About the data

- **Monthly only.** MDU publishes usage per billing month, not hourly or daily, so the Energy dashboard shows one bar per month.
- **Gas in GJ.** MDU bills Montana-Dakota and Great Plains gas in dekatherms (Dk). Home Assistant's gas device class only takes volume units, so gas is reported as energy in gigajoules. 1 Dk ≈ 1.055 GJ; the original Dk value is kept in the sensor attributes.
- **Refreshes twice a day.** New bills appear after MDU posts them.

## Installation

### HACS (recommended)

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add `https://github.com/bisman-automations/ha-mdu` with the category **Integration**.
3. Search for **Montana-Dakota Utilities** and download it.
4. Restart Home Assistant.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bisman-automations&repository=ha-mdu)

### Manual

Copy `custom_components/mdu` into your Home Assistant `config/custom_components` folder and restart.

## Setup

1. Go to **Settings → Devices & services → Add integration** and search for **Montana-Dakota Utilities**.
2. Enter your MDU Online Account Services username and password.
3. If your login has multi-factor authentication turned on, choose where MDU should send the security code, then enter the 5-digit code. Home Assistant asks MDU to trust this connection, so you normally won't be asked again.
4. If your login has more than one account, pick the account. Add the integration again for each other account.

If your password changes, or MDU stops trusting the connection, Home Assistant shows a **Reconfigure** prompt asking you to sign in again (with a new security code if MDU wants one).

## Troubleshooting

Turn on debug logging to see what the integration reads from the portal:

```yaml
logger:
  logs:
    custom_components.mdu: debug
```

If sensors are missing or values look wrong, open an issue and attach the integration's diagnostics: **Settings → Devices & services → Montana-Dakota Utilities → ⋮ → Download diagnostics**. Your credentials, account and service numbers and addresses are removed from that file automatically.

## How it works

The MDU portal is an Oracle CC&B self-service site. The integration signs in with the portal's own form (with its CSRF token), answers MFA the way the portal does with "trust this device" on, opens the configured account, and reads:

- `GET /session/user` for the balance, bills and service agreements
- `POST /usage-history` for each service agreement's monthly usage

## License

MIT. See [LICENSE](LICENSE).
