# AlphaOS Macro Agent Design

Date: 2026-07-23

## Goal

Add Macro Agent as an enabled, composable AlphaOS expert. Manager Agent may
select it when a request needs macroeconomic or industry-environment analysis,
but Macro is never a mandatory workflow node and is never added by executor
code.

Macro Agent answers:

- Whether the macro environment supports an industry or investment theme.
- Which macro factors are supportive.
- Which macro risks are material.

Macro Agent does not perform stock screening, company financial analysis,
technical analysis, price prediction, or trading recommendations.

## Architecture

Macro Agent follows the existing expert interface:

```text
ExpertTask
  -> MacroAgent.execute()
  -> PandaData catalog and macro data tools
  -> Ark structured planning and analysis
  -> ExpertResult
```

It exposes `execute(task)` and `__call__(task)` like the existing Research,
Quant, Risk, and Report agents. No `BaseAgent` or new agent framework is
introduced.

The existing orchestration boundaries remain unchanged:

- Registry is the single source of truth for expert availability.
- Manager selects Macro and its task-graph dependencies dynamically.
- WorkflowExecutor executes exactly the validated Manager graph.
- Executor registers a real Macro handler but never inserts a Macro step.
- Manager never selects Macro's internal PandaData queries.

## Registry And Manager

The existing `macro` registry entry becomes enabled. Its accepted inputs are:

- `industry`
- `time_range`
- `research_goal`
- `start_date`
- `end_date`

Its tools include `pandadata_macro_data`. Its capabilities remain focused on
macro, policy, and cycle analysis.

Manager prompt guidance states that Macro is appropriate for macro environment,
economic cycle, rates, liquidity, policy, and industry macro questions. It also
states that historical return calculations and other purely quantitative tasks
do not require Macro. This is prompt guidance, not keyword routing.

For explicit historical dates, Manager should normalize dates to `YYYYMMDD`.
When the user provides only a forward horizon, Macro Agent derives a historical
evidence window ending on the execution date and starting 24 months earlier.
The forward horizon remains the analysis horizon and is not represented as
observed PandaData.

## PandaData Integration

PandaData is the required external evidence source. Macro Agent must not
silently fall back to model-only analysis when PandaData is unavailable.

The client gains two narrowly scoped operations:

1. `get_macro_catalog(categories, fields)` calls `get_macro_detail`.
2. `get_macro_data(api_name, symbols, start_date, end_date, fields)` calls one
   reviewed macro endpoint.

PandaData documents macro endpoints for national accounts, industry, business
conditions, prices, investment, fiscal conditions, money and banking, rates
and foreign exchange, international economics, trade, employment, securities
markets, industry datasets, specialty datasets, and economic calendars.

Runtime calls use a static mapping of reviewed category codes, descriptions,
and `get_macro_*` methods. Model output cannot introduce an API method. The
client validates the method against this allowlist before using the SDK.

Every PandaData result passes through the existing `json_safe` conversion.
Macro Agent then applies bounded row counts, bounded strings, and an allowed
field projection before using the result.

## Dynamic Data Plan

Macro Agent uses three validated Ark stages.

### 1. Category Planning

Ark receives the task and the reviewed category allowlist. It returns a
`MacroDataPlan` containing:

- At most four category codes.
- At most eight indicator search terms.
- A bounded list of reasons for the selected dimensions.

Categories must belong to the allowlist. The plan cannot provide callable
method names.

### 2. Indicator Selection

Macro Agent calls `get_macro_detail` for the selected categories. It keeps
currently updated indicators and ranks them deterministically using:

- Model-provided search terms matched against indicator names.
- PandaData importance metadata.
- Current update status and end date.
- Balanced per-category limits.

At most 500 catalog candidates are sent to Ark. Ark returns a
`MacroIndicatorSelection` with at most eight symbols. Every symbol and its
`api_name` must exactly match the catalog returned during this execution.

### 3. Evidence Analysis

Macro Agent groups selected indicators by their catalog `api_name` and calls
the corresponding PandaData methods for the historical window.

For every usable time series Python calculates:

- Latest observation and period.
- Previous observation.
- Absolute change.
- Percentage change when the denominator permits it.
- Observation count.
- A bounded recent-observation tail.

Ark receives the task, selected indicator metadata, and deterministic series
summaries. It returns `MacroAnalysis` with:

- `conclusion`
- `economic_cycle`
- `interest_rate`
- `policy_factors`
- `liquidity`
- `market_environment`
- `positive_factors`
- `risks`

Policy factors without direct PandaData support must be marked as contextual
interpretation or omitted. The analysis prompt prohibits invented real-time
facts, stock-price predictions, and buy or sell advice.

## Validation And Repair

`MacroDataPlan`, `MacroIndicatorSelection`, and `MacroAnalysis` are Pydantic
models. All Ark output is untrusted until JSON parsing and model validation
succeed.

The whole Macro execution has one shared repair budget. A failed structured
stage may consume that one repair attempt. After it is consumed, any later
invalid structured response fails the task. Therefore a successful execution
uses three Ark calls, and an execution with repair uses at most four.

Catalog membership is checked after model validation. Indicator count,
category count, string lengths, and candidate payload size are bounded.

## ExpertResult Mapping

Code, rather than Ark, owns the uniform result envelope:

- `task_id` comes from `ExpertTask`.
- `agent` is always `macro`.
- `status` reflects actual execution.
- `summary` contains the validated macro conclusion.
- `evidence` contains selected indicator metadata and deterministic series
  summaries, explicitly identified as PandaData evidence.
- `assumptions` records the evidence-window and interpretation assumptions.
- `risks` contains the validated macro risks.
- `limitations` records unavailable dimensions, partial failures, publication
  lag, and forecast uncertainty.
- `recommendations` contains research-validation next steps only.
- `tool_calls` records catalog and macro data calls with bounded arguments and
  status.
- `data_sources` records PandaData API names, symbols, date windows, row counts,
  units, and original information sources where available.
- `metadata.macro_analysis` contains the complete validated analysis.
- `metadata.data_plan` records selected categories and indicators.

No credentials or unbounded raw datasets are stored in the result.

## Failure Behavior

Macro Agent returns a failed `ExpertResult` when:

- It receives a task assigned to another agent.
- Required task meaning cannot be established.
- PandaData configuration, authentication, or catalog retrieval fails.
- No valid catalog indicators can be selected.
- A model selects a category, symbol, or API outside the execution allowlist.
- All selected data queries fail or return no usable observations.
- A structured Ark stage remains invalid after the shared repair is exhausted.

If at least one selected indicator succeeds, partial PandaData failures may
produce a completed result. Failed calls and missing evidence are then listed
in `tool_calls` and `limitations`; Ark sees only the valid evidence.

External catalog text is treated as data, not instructions. Error messages are
sanitized and never expose credentials, raw provider exceptions, or secrets.

## Prompt

`backend/prompts/macro.md` defines Macro Agent as a macro investment research
expert. It requires analysis of:

1. Economic cycle.
2. Interest-rate environment.
3. Policy factors.
4. Liquidity.
5. Market environment.
6. Risks.

The prompt requires explicit separation between observed PandaData evidence
and forward-looking interpretation. It prohibits price predictions, specific
trading instructions, and unsupported claims of real-time knowledge.

## Testing

`tests/test_macro_agent.py` uses only Mock Ark and Mock PandaData.

Coverage includes:

- A renewable-energy request with a forward 12-month horizon derives the
  previous 24-month historical window, selects valid categories and indicators,
  calls catalog-provided endpoints, and returns a complete `ExpertResult`.
- A semiconductor trend request produces a valid Macro JSON structure with
  dynamically selected industry evidence.
- Registry exposes Macro to Manager while Portfolio remains disabled.
- Manager accepts a Macro plan for a macro industry request and a Quant-only
  plan for historical return analysis.
- Executor runs only the Manager-declared graph and has a real default Macro
  handler.
- Catalog-external categories, symbols, and API names are rejected.
- The three structured stages share exactly one repair attempt.
- Empty catalogs, missing configuration, and wholly empty data fail safely.
- Partial data failures preserve valid evidence and record limitations.
- Prompt and result boundaries prohibit price predictions and trade advice.

Automated tests never consume Ark or PandaData quota. A separate opt-in manual
integration script may exercise the real services while printing only bounded,
non-sensitive result metadata.

## Files

Implementation may modify or add:

- `backend/agents/macro_agent.py`
- `backend/prompts/macro.md`
- `backend/services/pandadata_client.py`
- `backend/core/agent_registry.py`
- `backend/core/workflow_executor.py`
- `backend/agents/manager_agent.py`
- `tests/test_macro_agent.py`
- `README.md`
- An optional explicit manual Macro integration script under `tests/`

No files are deleted.

## Acceptance Criteria

- Manager can discover and dynamically select Macro from Registry.
- Manager remains the sole outer orchestrator.
- Macro follows the existing expert interface and returns `ExpertResult`.
- Macro uses real PandaData macro catalog and time-series APIs.
- Ark performs bounded, validated data planning and macro analysis.
- Historical evidence and forward-looking interpretation are distinguishable.
- No external method can be invoked outside the reviewed allowlist.
- Automated tests mock Ark and PandaData and pass without consuming quota.
- Macro does not produce stock screening, price forecasts, or trading advice.
