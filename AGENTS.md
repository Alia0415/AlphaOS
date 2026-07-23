# AlphaOS Agent Guide

## Project goal

Build an autonomous multi-agent AI quant research organization in which specialized financial agents collaborate on research tasks.

## Multi-agent architecture

- The Intent Router Agent classifies requests and delegates work.
- The Research Agent gathers and synthesizes financial information.
- The Quant Agent performs reproducible quantitative analysis.
- The Risk Agent reviews assumptions, exposures, and failure modes.
- The Investment Manager Agent coordinates results and produces the final decision-ready response.

Agents should communicate through explicit, typed task and result contracts compatible with the A2A Agent Protocol.

## Development rules

- Keep modules small, typed, testable, and narrowly scoped.
- Separate agent orchestration, external services, and reusable skills.
- Add tests for behavior before expanding agent capabilities.
- Keep prompts and model configuration explicit and reviewable.
- Avoid unnecessary dependencies and generated files.

## QuantSkills integration principles

- Register QuantSkills through the central skill registry.
- Define clear inputs, outputs, assumptions, and error behavior for each skill.
- Prefer deterministic, reproducible calculations.
- Record data sources and calculation parameters.
- Treat model output as untrusted until validated.

## Security requirements

- Never expose API keys or commit secrets.
- Load credentials only from environment variables.
- Keep `.env` files out of version control.
- Redact secrets and sensitive financial data from logs.
- Validate external inputs and apply least-privilege access.

