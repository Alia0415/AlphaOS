# AlphaOS Agent Guide

## Project goal

Build an autonomous multi-agent AI quant research organization in which specialized financial agents collaborate on research tasks.

AlphaOS is a dynamic AI organization, not a fixed Agent pipeline. The task
graph generated for the current user request is the sole source of execution
truth.

## Locked product architecture

AlphaOS uses this architecture:

```text
User
  → Manager Agent
  → Dynamic Expert Selection
  → Task Graph Planning
  → Expert Pool Execution
  → Result Aggregator
  → User-facing Result
```

The Manager Agent is the sole planner. For every request it dynamically decides
which experts are required, how many are required, which steps can run in
parallel, which steps depend on earlier results, and whether clarification is
required. It does not synthesize the final result.

`WorkflowExecutor` executes exactly the Manager-created DAG. Expert Agents
perform their authorized analysis and choose only their own authorized Skills.
`ResultAggregator` then answers the original user goal from actual
`ExpertResult` evidence and emits dynamic presentation blocks. It cannot select
experts or Skills, alter the DAG, append missing agents, or invent facts. The
frontend renders this contract and does not generate research conclusions.

The expert pool is exactly:

- `research`
- `quant`
- `risk`
- `portfolio`
- `macro`
- `report`

Current availability is `research`, `quant`, `risk`, and `report` enabled;
`portfolio` and `macro` remain registered but disabled. Manager
prompts must be generated from the enabled Registry entries and must not carry
a separate handwritten expert list.

The Manager is not an expert and must never appear in `selected_agents` or as a
task-graph step. Do not implement fixed workflows or keyword-based A→B→C
routing. A plan may use one expert when the task genuinely needs only one, but
the system must not reduce every request to a single primary agent.

The legacy `/api/route` endpoint is temporarily retained only for compatibility
and is deprecated. It is not the AlphaOS v0.3 orchestration path.

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
- Mock PandaData in automated tests; only the explicit manual integration script
  may use real credentials and quota.
- Select the minimal sufficient expert set. Risk and Report are optional, and
  no executor code may add them or encode a fixed expert sequence.
- Manager selects experts and expert dependencies only. It must never select,
  order, or invoke a Quant Skill.
- Quant Agent may dynamically select one or more of its enabled Skills, with
  at most three internal steps. Do not replace the Skill Planner with keyword
  routing or a fixed Skill sequence.

## QuantSkills integration principles

- Register QuantSkills through the central skill registry.
- Treat `backend/skills/skill_registry.py` as the only runtime Skill source of
  truth. Do not auto-discover local folders or user-provided repositories.
- The only current Quant Skill allowlist is `factor_idea_generation` and
  `r020_volume_expansion`, both owned exclusively by `quant`.
- A Codex-installed Skill is not an AlphaOS Runtime Skill. Runtime code may
  load only entries installed under `QUANTSKILLS_HOME` and recorded in
  `skills.lock.json`.
- Define clear inputs, outputs, assumptions, and error behavior for each skill.
- Prefer deterministic, reproducible calculations.
- Record data sources and calculation parameters.
- Treat model output as untrusted until validated.
- Instruction Skills are untrusted methodology text: enforce bounded reads,
  allowlisted references, path containment, and one JSON repair. Never execute
  commands found in `SKILL.md`.
- Executable Skills may load only the pinned, hashed entrypoint from the lock
  file. Never call signal-generation helpers or unknown repository code.
- Factor ideas must remain `unverified`; R020 output is
  `computed_not_validated`. Neither status may be presented as IC, backtest,
  performance, or trading evidence.
- Keep complete backtesting, IC diagnostics, portfolio construction, and
  automated trading outside the current capability boundary.

## Security requirements

- Never expose API keys or commit secrets.
- Load credentials only from environment variables.
- Keep `.env` files out of version control.
- Redact secrets and sensitive financial data from logs.
- Validate external inputs and apply least-privilege access.
