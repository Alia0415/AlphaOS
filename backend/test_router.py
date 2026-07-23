"""Manual Router Agent test using the configured Volcano Ark model."""

from backend.agents.router_agent import RouterAgent


def main() -> None:
    decision = RouterAgent().route("分析贵州茅台近五年的盈利能力和行业竞争格局。")
    print(decision.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
