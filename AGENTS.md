# AlphaOS Agent Guide

## Project goal

Build an autonomous multi-agent AI quant research organization in which specialized financial agents collaborate on research tasks.

## Locked product architecture

AlphaOS uses this architecture:

```text
User
  → Manager Agent
  → Dynamic Expert Selection
  → Task Graph Planning
  → Expert Pool Execution
  → Manager Final Synthesis
```

The Manager Agent is the sole orchestrator. For every request it dynamically
decides which experts are required, how many are required, which steps can run
in parallel, which steps depend on earlier results, and whether clarification
is required.

The expert pool is exactly:

- `research`
- `quant`
- `risk`
- `portfolio`
- `macro`
- `report`

The Manager is not an expert and must never appear in `selected_agents` or as a
task-graph step. Do not implement fixed workflows or keyword-based A→B→C
routing. A plan may use one expert when the task genuinely needs only one, but
the system must not reduce every request to a single primary agent.

The legacy `/api/route` endpoint is temporarily retained only for compatibility
and is deprecated. It is not the AlphaOS v0.2 orchestration path.

Agents communicate through explicit Pydantic task and result contracts. Treat
all model-generated plans as untrusted until both structural and graph
validation succeed.

## Development rules

- Keep modules small, typed, testable, and narrowly scoped.
- Separate agent orchestration, external services, and reusable skills.
- Add tests for behavior before expanding agent capabilities.
- Keep prompts and model configuration explicit and reviewable.
- Avoid unnecessary dependencies and generated files.
- Limit model-output repair to one controlled attempt.
- Keep task graphs at eight steps or fewer and reject cycles or unknown agents.
- Mock ArkClient in automated tests; tests must never consume model API quota.

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
