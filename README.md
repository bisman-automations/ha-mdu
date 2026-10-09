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

| Statistic | Unit | Contents |
| --- | --- | --- |
| MDU Electric usage `<account>` `<service>` | kWh | Monthly electric usage |
| MDU Gas usage `<account>` `<service>` | GJ | Monthly gas usage |
| MDU bill cost `<account>` | USD | Each bill's total, by the month it was billed |

Usage covers every billed month MDU shows (about two years). Bills cover the whole account, so for an account with both electric and gas service the cost is their combined total. See [Energy dashboard setup](#energy-dashboard-setup) for where each one goes.

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

## 📊 Energy Dashboard Integration

Once configured, your MDU usage and bills appear in Home Assistant as monthly long-term statistics built for the Energy dashboard, alongside the visible sensors listed under [What you get](#what-you-get).

### Energy dashboard setup

The statistics appear in the Energy dashboard's pickers a few minutes after the integration's first refresh. Search for **MDU** to find them. Below, `<account>` and `<service>` stand for your account number and the service agreement number of the gas or electric service.

**Gas**

1. Go to **Settings** → **Dashboards** → **Energy**.
2. Under **Gas consumption**, select **Add gas source**.
3. For **Gas consumption**, pick **MDU Gas usage `<account>` `<service>`**.
4. For cost, choose **Use an entity tracking the total costs** and pick **MDU bill cost `<account>`**.
5. Optionally change the **Display name** (for example "Montana-Dakota Utilities"), then **Save**.

**Electric** (accounts with MDU electric service)

1. Under **Electricity grid**, select **Add consumption**.
2. For **Grid consumption**, pick **MDU Electric usage `<account>` `<service>`**.
3. For cost, choose **Use an entity tracking the total costs** and pick **MDU bill cost `<account>`**, unless the account also has gas service (see [Cost](#cost)).
4. Optionally change the **Display name**, then **Save**.

**What you'll see**

- **One bar per month.** MDU only publishes usage per billing month, so each month's usage sits on the 1st; day and week views show it all on that day.
- **Gas in kWh.** MDU bills gas in dekatherms (Dk). The integration records it as energy in GJ, and the Energy dashboard shows energy in kWh. 1 Dk ≈ 293 kWh ≈ 1.055 GJ, so divide the dashboard figure by 293 to compare with your bill.
- **The current month fills in late.** A month stays empty until MDU posts its bill.
- **Leave the other fields empty.** **Gas flow rate** isn't used; there's no solar return data from MDU.

#### Cost

Each account gets one **bill cost** statistic (`mdu:<account>_bill_cost`, in USD): every bill's total, placed on the month it was billed. It includes everything on the bill, such as the customer charge and taxes, so a month's cost matches the bill exactly.

Bills cover the whole account. For an account with both electric and gas service, the bill cost is their combined total: add it to one source only, or the Energy dashboard counts it twice.

### History

On setup the integration imports every month MDU shows: about two years of usage and the last twelve bills. From then on it adds each new month as MDU posts it, so history keeps growing. Because MDU shows fewer bills than months of usage, a view reaching back more than a year shows usage with no cost for the oldest months.

### Sensor Details

- **Device Class**: Energy for both electric and gas usage (Home Assistant's gas device class only accepts volume units)
- **State Class**: none on the visible "last month" sensors; the imported statistics are cumulative sums for dashboard use
- **Unit**: kWh for electric usage, GJ for gas usage (the original Dk value is in the `source_value` attribute)
- **Icon**: Lightning bolt (mdi:flash) for electric usage, flame (mdi:fire) for gas usage

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
