from __future__ import annotations

import math
import os
from threading import Lock
from typing import Any


class PandaDataConfigurationError(RuntimeError):
    """Raised when PandaData is unavailable or incorrectly configured."""


class PandaDataClient:
    """Lazy, thread-safe adapter for the PandaData Python SDK."""

    def __init__(self) -> None:
        self._sdk: Any | None = None
        self._authenticated_as: str | None = None
        self._lock = Lock()

    @property
    def configured(self) -> bool:
        return bool(
            os.getenv("PANDADATA_USERNAME") and os.getenv("PANDADATA_PASSWORD")
        )

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "authenticated": self._authenticated_as is not None,
            "username_hint": self._username_hint(),
        }

    def get_market_data(
        self,
        *,
        symbols: list[str],
        start_date: str,
        end_date: str,
        fields: list[str],
        indicator: str,
        st: bool,
    ) -> Any:
        sdk = self._authenticate()
        result = sdk.get_market_data(
            symbol=symbols,
            start_date=start_date,
            end_date=end_date,
            type="stock",
            fields=fields,
            indicator=indicator,
            st=st,
        )
        return json_safe(result)

    def _authenticate(self) -> Any:
        username = os.getenv("PANDADATA_USERNAME", "").strip()
        password = os.getenv("PANDADATA_PASSWORD", "")
        if not username or not password:
            raise PandaDataConfigurationError(
                "PandaData 未配置，请设置 PANDADATA_USERNAME 和 "
                "PANDADATA_PASSWORD 环境变量。"
            )
        if not username.startswith("86"):
            raise PandaDataConfigurationError(
                "PANDADATA_USERNAME 必须是 86 开头的官网注册手机号。"
            )

        with self._lock:
            if self._sdk is not None and self._authenticated_as == username:
                return self._sdk
            try:
                import panda_data
            except ImportError as exc:
                raise PandaDataConfigurationError(
                    "缺少 panda_data SDK，请运行 pip install -r requirements.txt。"
                ) from exc

            panda_data.init_token(username=username, password=password)
            self._sdk = panda_data
            self._authenticated_as = username
            return panda_data

    def _username_hint(self) -> str | None:
        username = os.getenv("PANDADATA_USERNAME", "").strip()
        if not username:
            return None
        if len(username) <= 6:
            return username[:2] + "***"
        return f"{username[:4]}***{username[-3:]}"


def json_safe(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        try:
            value = value.to_dict(orient="records")
        except TypeError:
            value = value.to_dict()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)
