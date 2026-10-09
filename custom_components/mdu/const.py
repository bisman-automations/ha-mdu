"""Constants for the Montana-Dakota Utilities integration."""

from datetime import timedelta

DOMAIN = "mdu"

# Configuration keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_ACCOUNT_ID = "account_id"
CONF_HOST = "host"
CONF_TRUSTED_COOKIES = "trusted_cookies"
CONF_MFA_CONTACT = "mfa_contact"
CONF_MFA_CODE = "mfa_code"

DEFAULT_HOST = "customer.montana-dakota.com"

# MDU only publishes monthly figures, so there is no point polling often.
UPDATE_INTERVAL = timedelta(hours=12)

REQUEST_TIMEOUT = 30  # seconds

# Units the portal reports, chosen the same way the portal's usage chart picks
# its axis label (see MDUClient.usage_unit).
UNIT_KWH = "kWh"
UNIT_DEKATHERM = "Dk"
UNIT_THERM = "therms"

# 1 therm = 100,000 BTU = 29.3071 kWh; 1 dekatherm = 10 therms.
KWH_PER_THERM = 29.3071
KWH_PER_DEKATHERM = KWH_PER_THERM * 10

ATTR_ACCOUNT_ID = "account_id"
ATTR_SA_ID = "service_agreement_id"
ATTR_PREMISE_ID = "premise_id"
ATTR_SERVICE_ADDRESS = "service_address"
ATTR_BILLING_MONTH = "billing_month"
ATTR_SOURCE_UNIT = "source_unit"
ATTR_SOURCE_VALUE = "source_value"
ATTR_LAST_YEAR = "same_month_last_year"
