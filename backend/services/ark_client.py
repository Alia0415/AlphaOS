"""Reusable Volcano Ark model client."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from openai import OpenAI

ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_ARK_MODEL = "ep-20260708162855-pcf9x"


class ArkClientError(RuntimeError):
    """Raised when an Ark model request cannot be completed."""


class ArkClient:
    """Small adapter around the Volcano Ark OpenAI-compatible API."""

    def __init__(self) -> None:
        load_dotenv()
        api_key = os.getenv("ARK_API_KEY", "").strip()
        if not api_key:
            raise ArkClientError(
                "未找到 ARK_API_KEY，请先配置环境变量或本地 .env 文件。"
            )

        self._model = os.getenv("ARK_MODEL", "").strip() or DEFAULT_ARK_MODEL
        self._client = OpenAI(base_url=ARK_BASE_URL, api_key=api_key)

    def chat(self, prompt: str, model: str | None = None) -> str:
        """Send a text prompt and return the model's text response."""
        selected_model = model or self._model
        try:
            response = self._client.responses.create(
                model=selected_model,
                input=prompt,
            )
        except Exception:
            raise ArkClientError("Volcano Ark API 请求失败。") from None

        output_text = response.output_text
        if not output_text or not output_text.strip():
            raise ArkClientError("Volcano Ark API 返回了空响应。")
        return output_text
