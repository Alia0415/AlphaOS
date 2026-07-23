"""Manual connectivity test for the Volcano Ark model service."""

import sys

from backend.services.ark_client import ArkClient


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    prompt = """
你是AlphaOS系统中的AI投资研究负责人。

请简单介绍你的能力。
"""
    response = ArkClient().chat(prompt)
    print(response)


if __name__ == "__main__":
    main()
