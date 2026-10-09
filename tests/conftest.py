"""Fixtures for Montana-Dakota Utilities tests."""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    text = (FIXTURES / name).read_text()
    return json.loads(text) if name.endswith(".json") else text


@pytest.fixture(autouse=True)
def base_recorder_fixture(recorder_mock, enable_custom_integrations):
    """Every test gets a recorder and custom integrations enabled."""
