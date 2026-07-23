from __future__ import annotations

import math
import os
import re
from pathlib import Path
from threading import Lock
from typing import Any

from dotenv import load_dotenv

ALPHAOS_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
SYMBOL_PATTERN = re.compile(r"^\d{6}\.(?:SH|SZ)$")
QUARTER_PATTERN = re.compile(r"^(\d{4})q([1-4])$", re.IGNORECASE)
DATE_PATTERN = re.compile(r"^\d{8}$")

MACRO_DATASETS: dict[str, tuple[str, str]] = {
    "NA": ("get_macro_na", "国民经济核算"),
    "IN": ("get_macro_in", "工业"),
    "CI": ("get_macro_ci", "景气指数"),
    "PI": ("get_macro_pi", "价格指数"),
    "FA": ("get_macro_fa", "固定资产投资"),
    "FI": ("get_macro_fi", "财政"),
    "MB": ("get_macro_mb", "货币与银行"),
    "IR": ("get_macro_ir", "利率汇率"),
    "FE": ("get_macro_fe", "对外经济"),
    "DT": ("get_macro_dt", "国内贸易"),
    "EW": ("get_macro_ew", "就业与工资"),
    "LI": ("get_macro_li", "人民生活"),
    "PR": ("get_macro_pr", "人口与资源"),
    "SE": ("get_macro_se", "科教体卫"),
    "SM": ("get_macro_sm", "证券市场"),
    "PM": ("get_macro_pm", "区域宏观"),
    "GB": ("get_macro_gb", "国际宏观"),
    "AG": ("get_macro_ag", "农林牧渔"),
    "EN": ("get_macro_en", "能源"),
    "CH": ("get_macro_ch", "化工"),
    "ST": ("get_macro_st", "钢铁"),
    "NF": ("get_macro_nf", "有色金属"),
    "BM": ("get_macro_bm", "建材"),
    "AU": ("get_macro_au", "汽车"),
    "ME": ("get_macro_me", "机械设备"),
    "EE": ("get_macro_ee", "电子电器"),
    "TM": ("get_macro_tm", "TMT"),
    "FB": ("get_macro_fb", "食品饮料"),
    "TE": ("get_macro_te", "纺织服装"),
    "PP": ("get_macro_pp", "造纸印刷"),
    "PH": ("get_macro_ph", "医药生物"),
    "UT": ("get_macro_ut", "公用事业"),
    "TR": ("get_macro_tr", "交通运输"),
    "RC": ("get_macro_rc", "房地产及建筑业"),
    "TH": ("get_macro_th", "旅游酒店"),
    "CE": ("get_macro_ce", "文教体娱及工艺品"),
    "WR": ("get_macro_wr", "批发零售业"),
    "FS": ("get_macro_fs", "金融保险业"),
    "IS": ("get_macro_is", "行业综合"),
    "EC": ("get_macro_ec", "线上电商"),
    "MD": ("get_macro_md", "医药特色"),
    "EH": ("get_macro_eh", "能化特色"),
    "AD": ("get_macro_ad", "汽车特色"),
    "HA": ("get_macro_ha", "家电特色"),
    "OF": ("get_macro_of", "线下商超"),
    "RB": ("get_macro_rb", "招聘"),
    "RE": ("get_macro_re", "房地产特色"),
    "ED": ("get_macro_ed", "电子特色"),
    "EP": ("get_macro_ep", "电力与新能源"),
    "AR": ("get_macro_ar", "农业特色"),
    "CM": ("get_macro_cm", "大宗商品"),
}

MACRO_API_ALLOWLIST = frozenset(
    api_name for api_name, _ in MACRO_DATASETS.values()
)


class PandaDataConfigurationError(RuntimeError):
    """Raised when PandaData is unavailable or incorrectly configured."""


class PandaDataClient:
    """Lazy, thread-safe adapter for the PandaData Python SDK."""

    def __init__(self) -> None:
        load_dotenv(dotenv_path=ALPHAOS_ENV_FILE)
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

    def get_macro_catalog(
        self,
        *,
        categories: list[str],
        fields: list[str],
    ) -> Any:
        invalid = set(categories) - set(MACRO_DATASETS)
        if not categories or invalid:
            raise ValueError("Macro categories are not allowlisted.")
        sdk = self._authenticate()
        return json_safe(
            sdk.get_macro_detail(category=categories, fields=fields)
        )

    def get_macro_data(
        self,
        *,
        api_name: str,
        symbols: list[str],
        start_date: str,
        end_date: str,
        fields: list[str],
    ) -> Any:
        if api_name not in MACRO_API_ALLOWLIST:
            raise ValueError("Macro API is not allowlisted.")
        sdk = self._authenticate()
        endpoint = getattr(sdk, api_name, None)
        if not callable(endpoint):
            raise PandaDataConfigurationError(
                "PandaData SDK does not expose the requested macro API."
            )
        return json_safe(
            endpoint(
                symbol=symbols,
                start_date=start_date,
                end_date=end_date,
                fields=fields,
            )
        )

    def get_fina_reports(
        self,
        *,
        symbol: str,
        start_period: str,
        end_period: str,
        fields: list[str] | None = None,
    ) -> Any:
        symbol = _validate_symbol(symbol)
        start_period, end_period = _validate_period_range(
            start_period,
            end_period,
        )
        return self._call(
            "get_fina_reports",
            symbol=symbol,
            start_quarter=start_period,
            end_quarter=end_period,
            fields=fields,
            is_latest=False,
        )

    def get_fina_performance(
        self,
        *,
        symbol: str,
        end_period: str,
        fields: list[str] | None = None,
    ) -> Any:
        return self._call(
            "get_fina_performance",
            symbol=_validate_symbol(symbol),
            end_quarter=_validate_period(end_period),
            fields=fields,
        )

    def get_fina_forecast(
        self,
        *,
        symbol: str,
        end_period: str,
        fields: list[str] | None = None,
    ) -> Any:
        return self._call(
            "get_fina_forecast",
            symbol=_validate_symbol(symbol),
            end_quarter=_validate_period(end_period),
            fields=fields,
        )

    def get_audit_opinion(
        self,
        *,
        symbol: str,
        start_period: str,
        end_period: str,
        fields: list[str] | None = None,
    ) -> Any:
        symbol = _validate_symbol(symbol)
        start_period, end_period = _validate_period_range(
            start_period,
            end_period,
        )
        return self._call(
            "get_audit_opinion",
            symbol=symbol,
            start_quarter=start_period,
            end_quarter=end_period,
            market="cn",
            fields=fields,
        )

    def get_stock_detail(self, *, symbol: str) -> Any:
        return self._call("get_stock_detail", symbol=_validate_symbol(symbol))

    def get_stock_industry(self, *, symbol: str) -> Any:
        return self._call(
            "get_stock_industry",
            stock_symbol=_validate_symbol(symbol),
            level="L1",
        )

    def get_stock_dividend(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_stock_dividend",
            symbol,
            start_date,
            end_date,
            market="cn",
        )

    def get_share_float(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call("get_share_float", symbol, start_date, end_date)

    def get_stock_status_change(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_stock_status_change",
            symbol,
            start_date,
            end_date,
        )

    def get_stock_cash_dividend(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_stock_cash_dividend",
            symbol,
            start_date,
            end_date,
            market="cn",
        )

    def get_stock_dividend_amount(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_stock_dividend_amount",
            symbol,
            start_date,
            end_date,
            market="cn",
        )

    def get_repurchase(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call("get_repurchase", symbol, start_date, end_date)

    def get_stock_private_placement(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_stock_private_placement",
            symbol,
            start_date,
            end_date,
            market="cn",
        )

    def get_stock_allotment(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_stock_allotment",
            symbol,
            start_date,
            end_date,
            market="cn",
        )

    def get_stock_split(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_stock_split",
            symbol,
            start_date,
            end_date,
            market="cn",
        )

    def get_investor_activity(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_investor_activity",
            symbol,
            start_date,
            end_date,
        )

    def get_top_holders(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_top_holders",
            symbol,
            start_date,
            end_date,
            market="cn",
        )

    def get_holder_count(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_holder_count",
            symbol,
            start_date,
            end_date,
        )

    def get_stock_pledge(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_stock_pledge",
            symbol,
            start_date,
            end_date,
        )

    def get_stock_shareholder_change(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_stock_shareholder_change",
            symbol,
            start_date,
            end_date,
        )

    def get_restricted_list(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_restricted_list",
            symbol,
            start_date,
            end_date,
            market="cn",
        )

    def get_stock_daily(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call(
            "get_stock_daily",
            symbol,
            start_date,
            end_date,
            fields=["trade_date", "symbol", "close", "volume"],
            indicator="000300",
            st=True,
        )

    def get_lhb_list(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call("get_lhb_list", symbol, start_date, end_date)

    def get_lhb_detail(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call("get_lhb_detail", symbol, start_date, end_date)

    def get_block_trade(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call("get_block_trade", symbol, start_date, end_date)

    def get_margin(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call("get_margin", symbol, start_date, end_date)

    def get_hsgt_hold(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Any:
        return self._dated_call("get_hsgt_hold", symbol, start_date, end_date)

    def _dated_call(
        self,
        method: str,
        symbol: str,
        start_date: str,
        end_date: str,
        **kwargs: Any,
    ) -> Any:
        symbol = _validate_symbol(symbol)
        start_date, end_date = _validate_date_range(start_date, end_date)
        return self._call(
            method,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            **kwargs,
        )

    def _call(self, method: str, **kwargs: Any) -> Any:
        sdk = self._authenticate()
        function = getattr(sdk, method, None)
        if not callable(function):
            raise PandaDataConfigurationError(
                f"PandaData SDK 不支持受控方法 {method}。"
            )
        return json_safe(function(**kwargs))

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


def _validate_symbol(symbol: str) -> str:
    normalized = str(symbol).strip().upper()
    if not SYMBOL_PATTERN.fullmatch(normalized):
        raise ValueError("股票代码必须是 XXXXXX.SH 或 XXXXXX.SZ。")
    return normalized


def _validate_period(period: str) -> str:
    normalized = str(period).strip().lower()
    if not QUARTER_PATTERN.fullmatch(normalized):
        raise ValueError("财务报告期必须是 YYYYqN 格式。")
    return normalized


def _validate_period_range(start_period: str, end_period: str) -> tuple[str, str]:
    start = _validate_period(start_period)
    end = _validate_period(end_period)
    start_match = QUARTER_PATTERN.fullmatch(start)
    end_match = QUARTER_PATTERN.fullmatch(end)
    assert start_match is not None and end_match is not None
    start_index = int(start_match.group(1)) * 4 + int(start_match.group(2))
    end_index = int(end_match.group(1)) * 4 + int(end_match.group(2))
    if start_index > end_index:
        raise ValueError("start_period 不能晚于 end_period。")
    if end_index - start_index > 20:
        raise ValueError("财务查询窗口不能超过五年。")
    return start, end


def _validate_date_range(start_date: str, end_date: str) -> tuple[str, str]:
    start = str(start_date).strip()
    end = str(end_date).strip()
    if not DATE_PATTERN.fullmatch(start) or not DATE_PATTERN.fullmatch(end):
        raise ValueError("日期必须是 YYYYMMDD 格式。")
    if start > end:
        raise ValueError("start_date 不能晚于 end_date。")
    return start, end
