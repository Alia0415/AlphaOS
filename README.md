# AlphaOS v0.3 + Skill Runtime

AlphaOS is a dynamic AI research organization, not a fixed Agent or Skill
pipeline. The outer task graph remains the sole source of truth for expert
execution; each expert owns any internal capability selection.

## Architecture

```text
User
  → Manager Agent
  → Dynamic Expert Selection
  → Dynamic Task Graph
  → Quant Agent (only when selected)
      → Quant Skill Planner
      → Allowlisted QuantSkills Runtime
  → optional Risk / Report (only when selected)
  → Result Aggregator
  → Dynamic User-facing Result
```

Manager chooses experts and expert dependencies only. It cannot select or
invoke a bottom-level Skill. Quant Agent sees only its own enabled Skills and
dynamically selects the minimal sufficient set, with at most three internal
steps and no fixed Skill sequence.

`WorkflowExecutor` runs exactly the validated Manager DAG. The independent
`ResultAggregator` inspects only actual `ExpertResult` contracts, determines
completion status, answers the original goal, and emits evidence-driven content
blocks. The frontend renders only returned blocks, so an uncalled expert never
creates an empty or implied section. Complete expert results remain available
under `aggregation.technical_evidence`.

The enabled expert pool is:

| Expert | Enabled | Current responsibility |
| --- | --- | --- |
| `research` | yes | PandaData market research and deterministic metrics |
| `quant` | yes | Factor hypotheses and pinned R020 computation |
| `risk` | yes | Independent or dependency-based risk review |
| `report` | yes | Optional integration of declared upstream results |
| `portfolio` | no | Reserved; no implementation |
| `macro` | no | Reserved; no implementation |

Quant is never automatically added to a request. Risk and Report are never
automatically appended to Quant. The executor runs exactly the Manager-created
DAG, while Quant executes its own validated Skill DAG internally.

## Current Skill Runtime

`backend/skills/skill_registry.py` is the sole runtime Skill allowlist:

| Skill ID | Mode | Owner | Source | License | Status meaning |
| --- | --- | --- | --- | --- | --- |
| `factor_idea_generation` | instruction | `quant` | `quantskills/skill-factor-idea-generation` | GPL-3.0-only | hypotheses remain `unverified` |
| `r020_volume_expansion` | executable | `quant` | `quantskills/skill-quant-factor-volume-stat-alpha` R020 | GPL-3.0-only | `computed_not_validated` |

An installed Codex Skill is not automatically installed for the AlphaOS
service. AlphaOS reads runtime Skills only from `QUANTSKILLS_HOME`, verifies
them against `skills.lock.json`, and loads only the expected entrypoint.
Local folders and user-supplied repositories are not auto-discovered.

Instruction Skill Markdown is treated as untrusted methodology text. The
loader enforces path containment, an explicit references allowlist, a bounded
text size, and never executes commands found in documentation. Ark output is
validated with Pydantic and receives at most one JSON repair attempt.

R020 loads the pinned and hashed
`factors/R020-5d-z-scored-volume-expansion/scripts/factor.py`, calls only
`compute_factor(df)`, and operates on PandaData OHLCV supplied by Quant Agent.
It does not call the upstream `generate_signals`, use bundled validation data,
or modify external Skill source.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Installs only the two fixed repositories and refreshes skills.lock.json.
python scripts\install_selected_skills.py

$env:ARK_API_KEY = "your-volcano-ark-key"
$env:ARK_MODEL = "your-endpoint-id" # optional
$env:PANDADATA_USERNAME = "8617777777777"
$env:PANDADATA_PASSWORD = "your-pandaai-password"

uvicorn backend.main:app --reload
```

Then open the local demo console:

```text
http://127.0.0.1:8000/
```

The frontend has no Node.js build step. Its default **Demo mode** uses clearly
labelled local example responses so the orchestration UI can be presented
without external credentials. **Live API mode** calls the existing
`POST /api/tasks` endpoint and therefore requires Ark configuration; tasks
that fetch market data also require PandaData credentials. The interactive API
documentation remains available at `http://127.0.0.1:8000/docs`.

The default result view first shows `aggregation.direct_answer`, then renders
only `aggregation.content_blocks`. Possible block types include metrics,
comparisons, factor ideas, risks, limitations, reports, clarification, and
failures, but none is mandatory. The separate professional-evidence view
retains the dynamic task graph, complete expert contracts, raw validation
states, provenance, and technical execution events. Both views are
deterministic presentations of the same response; no research evidence is
generated in the browser.

The default runtime directory is `AlphaOS/.runtime_skills`, which is ignored
by Git. Override it with an absolute path or a path relative to `AlphaOS`:

```powershell
$env:QUANTSKILLS_HOME = "D:\runtime\quantskills"
python scripts\install_selected_skills.py --runtime-home $env:QUANTSKILLS_HOME
```

`skills.lock.json` is committed and records repository, commit SHA, Skill path,
license, installation timestamp, expected entrypoint, and entrypoint SHA-256.
The external repositories are GPL-3.0-only; keep their copyright and license
notices, preserve provenance in every result, and review GPL distribution
obligations before packaging or redistributing a combined service.

## API examples

`POST /api/plan` returns a validated expert DAG without running it:

```bash
curl -X POST "http://127.0.0.1:8000/api/plan" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"请根据 OHLCV 数据提出几个可验证的量价因子想法。\"}"
```

### Quant only: factor ideas

```bash
curl -X POST "http://127.0.0.1:8000/api/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"请根据 OHLCV 数据生成 5 个可验证因子想法并 shortlist 2 个。\"}"
```

Expected outer graph: `quant`. Quant may select only
`factor_idea_generation`. Results explicitly state that ideas are unverified,
IC has not been calculated, no backtest has run, and no trading signal exists.

### Quant only: actual R020 calculation

```bash
curl -X POST "http://127.0.0.1:8000/api/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"计算 000001.SZ、000002.SZ 和 600519.SH 在 2024 年的 R020 成交量放大因子。\"}"
```

Expected outer graph: `quant`. Manager must extract `symbols`, `start_date`,
and `end_date`; Quant then fetches PandaData OHLCV and invokes the pinned R020
`compute_factor`. Missing required inputs cause a clarification request rather
than guessed values.

### Quant → Risk

```bash
curl -X POST "http://127.0.0.1:8000/api/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"计算 000001.SZ、000002.SZ 和 600519.SH 在 2024 年的 R020，并审查主要失效风险。\"}"
```

Expected outer graph: `quant → risk`. Risk receives the Quant factor
definition, coverage, assumptions, limitations, validation status, and
provenance. It does not reinterpret an unvalidated computation as performance.

When a user explicitly requests both risk review and a report, Manager may
create `quant → risk → report`; when only a research summary is requested it
may create `quant → report`. These are acceptance scenarios, not hardcoded
routes.

## Events and result contracts

`POST /api/tasks` returns the original `plan`, `events`, and `results` plus an
`aggregation` object with:

- `user_goal`, `completion_status`, and `output_mode`
- a plain-language `direct_answer`
- zero or more evidence-driven `content_blocks`
- an optional `execution_summary`
- complete, collapsible `technical_evidence`

The compatibility `final_answer` field remains available and is derived from
`aggregation.direct_answer`; Manager no longer produces it.

The outer lifecycle includes `plan_created`, expert step events, optional
legacy-named `synthesis_started` (now emitted by `ResultAggregator`), and
`task_completed`. Quant can additionally emit:

- `skill_plan_created`
- `skill_started`
- `skill_completed`
- `skill_failed`

Each Skill event includes the parent expert `step_id`, agent, Skill ID, and
bounded metadata. Events never include complete `SKILL.md`, raw market data,
or credentials.

Every Quant `ExpertResult` records actual Skills, complete `SkillResult`
objects, data sources, assumptions, limitations, `validation_status`, and
source provenance. Failed and unavailable Skill results include an error.

## Testing

Automated tests mock Ark and PandaData and never consume API quota:

```powershell
python -m pytest -q tests
```

The suite covers the allowlist and ownership boundary, disabled and missing
Skills, loader traversal protection, structured unverified factor ideas,
single repair, actual `compute_factor` dispatch, OHLCV validation, provenance,
Quant-only and Quant-to-Risk paths, safe events, and credential redaction.

For the opt-in real PandaData + R020 smoke test:

```powershell
python tests\manual_test_quant_runtime.py
```

It requests three symbols for 2024 and prints only bounded factor metadata,
never raw OHLCV or credentials. If credentials are absent, it reports
`skipped` rather than substituting fixture or upstream validation data.

The existing dynamic expert smoke test remains:

```powershell
python tests\manual_test_dynamic_execution.py
```

## Explicit capability boundary

Currently supported:

- Research
- Risk
- Report
- Quant factor idea generation
- Quant R020 factor computation

Not currently supported:

- Complete factor backtesting
- Multidimensional IC diagnostics
- Portfolio Agent or Macro Agent
- Automatic trading, order placement, or buy/sell recommendations
- Dynamic execution of unknown GitHub code

All output is research-only and does not constitute investment advice,
security recommendations, or a return promise.
