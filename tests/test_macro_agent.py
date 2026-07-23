from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from backend.services.pandadata_client import PandaDataClient


class FakePandaSDK:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_macro_detail(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("get_macro_detail", kwargs))
        return [{"symbol": "CI0000001", "name": "制造业PMI"}]

    def get_macro_ci(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("get_macro_ci", kwargs))
        return [
            {
                "symbol": "CI0000001",
                "period_date": "20260630",
                "data_value": 50.4,
            }
        ]


def test_pandadata_macro_catalog_uses_reviewed_detail_endpoint() -> None:
    sdk = FakePandaSDK()
    client = PandaDataClient()

    with patch.object(client, "_authenticate", return_value=sdk):
        result = client.get_macro_catalog(
            categories=["CI", "MB"],
            fields=["symbol", "name", "api_name"],
        )

    assert result == [{"symbol": "CI0000001", "name": "制造业PMI"}]
    assert sdk.calls == [
        (
            "get_macro_detail",
            {
                "category": ["CI", "MB"],
                "fields": ["symbol", "name", "api_name"],
            },
        )
    ]


def test_pandadata_macro_data_dispatches_only_allowlisted_api() -> None:
    sdk = FakePandaSDK()
    client = PandaDataClient()

    with patch.object(client, "_authenticate", return_value=sdk):
        result = client.get_macro_data(
            api_name="get_macro_ci",
            symbols=["CI0000001"],
            start_date="20240723",
            end_date="20260723",
            fields=["symbol", "period_date", "data_value"],
        )

    assert result[0]["data_value"] == 50.4
    assert sdk.calls == [
        (
            "get_macro_ci",
            {
                "symbol": ["CI0000001"],
                "start_date": "20240723",
                "end_date": "20260723",
                "fields": ["symbol", "period_date", "data_value"],
            },
        )
    ]


def test_pandadata_macro_data_rejects_unknown_api_before_authentication() -> None:
    client = PandaDataClient()

    with (
        patch.object(
            client,
            "_authenticate",
            side_effect=AssertionError("must not authenticate"),
        ),
        pytest.raises(ValueError, match="not allowlisted"),
    ):
        client.get_macro_data(
            api_name="delete_everything",
            symbols=["CI0000001"],
            start_date="20240723",
            end_date="20260723",
            fields=[],
        )
