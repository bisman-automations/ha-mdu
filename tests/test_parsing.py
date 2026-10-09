"""Tests for parsing portal responses."""
from datetime import date

import pytest

from custom_components.mdu.api import (
    ServiceAgreement,
    parse_account,
    parse_date,
    parse_money,
    parse_month_label,
    parse_usage,
    usage_unit,
)

from .conftest import load_fixture

TODAY = date(2026, 10, 9)
SA = ServiceAgreement("5550001", "7770001")


def test_parse_account() -> None:
    account = parse_account(load_fixture("session_user.json")["selectedAccount"])
    assert account.account_id == "1234567890"
    assert account.description == "Home"
    assert account.account_balance == 182.45
    assert account.amount_due == 182.45
    assert account.last_bill_amount == 182.45
    assert account.last_bill_date == date(2026, 9, 14)
    assert account.due_date == date(2026, 10, 8)
    assert [sa.sa_id for sa in account.service_agreements] == ["5550001", "5550002"]
    assert account.service_agreements[0].premise_id == "7770001"
    assert account.service_agreements[0].address == "123 Main St, Bismarck ND"


def test_parse_usage_with_years() -> None:
    history = parse_usage(SA, load_fixture("usage_electric.json")["object"], TODAY)
    assert history.unit == "kWh"
    assert not history.is_gas
    # Oct 2025 – Dec 2025 come from last year's column, Jan – Sep 2026 from this year's.
    assert history.months[0].month == date(2025, 1, 1)
    assert history.latest.month == date(2026, 9, 1)
    assert history.latest.value == 830
    assert history.value_for(date(2025, 9, 1)) == 800
    assert history.value_for(date(2025, 12, 1)) == 860
    # The unbilled current month (0) is dropped.
    assert history.value_for(date(2026, 10, 1)) is None
    assert len(history.months) == 21


def test_parse_usage_calendar_chart_without_years() -> None:
    history = parse_usage(SA, load_fixture("usage_gas.json")["object"], TODAY)
    assert history.unit == "Dk"
    assert history.is_gas
    assert history.latest.month == date(2026, 9, 1)
    assert history.latest.value == 2.0
    # Future months in "this year" are empty, so Nov/Dec last year are 2025.
    assert history.value_for(date(2025, 11, 1)) == 11.8
    assert history.value_for(date(2024, 11, 1)) is None


def test_parse_usage_rolling_chart_without_years() -> None:
    obj = {
        "glDivision": "MDU",
        "saType": "Electric",
        "usageYearComparisonChartList": [
            {"month": "Nov", "tyTherms": 700, "lyTherms": 690},
            {"month": "Dec", "tyTherms": 860, "lyTherms": 840},
            {"month": "Sep", "tyTherms": 830, "lyTherms": 800},
        ],
    }
    history = parse_usage(SA, obj, TODAY)
    # "This year" has November figures in October, so the chart is rolling.
    assert history.value_for(date(2025, 11, 1)) == 700
    assert history.value_for(date(2024, 11, 1)) == 690
    assert history.latest.month == date(2026, 9, 1)


@pytest.mark.parametrize(
    ("division", "sa_type", "unit"),
    [
        ("MDU", "Electric", "kWh"),
        ("MDU", "Gas", "Dk"),
        ("GPG", "Gas", "Dk"),
        ("CNG", "Gas", "therms"),
        (None, None, "therms"),
    ],
)
def test_usage_unit(division, sa_type, unit) -> None:
    assert usage_unit(division, sa_type) == unit


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Jan-2026", (1, 2026)),
        ("Jan-26", (1, 2026)),
        ("January 2026", (1, 2026)),
        ("01-2026", (1, 2026)),
        ("2026-01", (1, 2026)),
        ("Sep", (9, None)),
        ("", None),
        (None, None),
    ],
)
def test_parse_month_label(label, expected) -> None:
    assert parse_month_label(label) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-08", date(2026, 10, 8)),
        ("10/08/2026", date(2026, 10, 8)),
        ("2026-10-08T00:00:00.000-05:00", date(2026, 10, 8)),
        (1791417600000, date(2026, 10, 8)),
        ("", None),
        ("soon", None),
    ],
)
def test_parse_date(value, expected) -> None:
    assert parse_date(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("$1,234.50", 1234.5), ("45.10CR", -45.1), ("(12.00)", -12.0), (99, 99.0), (None, None)],
)
def test_parse_money(value, expected) -> None:
    assert parse_money(value) == expected
