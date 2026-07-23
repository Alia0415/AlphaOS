# AlphaOS v0.2

**AlphaOS: Dynamic Multi-Agent Planning Kernel**

AlphaOS is an autonomous AI quant research organization. Version 0.2 replaces
single-agent routing with Manager-generated, dependency-aware execution plans.

## Architecture

```text
User
  → Manager Agent
  → Dynamic Expert Selection
  → Task Graph Planning
  → Expert Pool Execution
  → Manager Final Synthesis
```

The Manager is the orchestrator, not an expert. It asks Volcano Ark to select
the necessary experts and create a JSON task graph for each request. Plans are
validated with Pydantic and semantic graph checks before execution.

The expert pool contains:

| Expert | Responsibility |
| --- | --- |
| `research` | Company, industry, and fundamental research |
| `quant` | Quantitative analysis and verifiable strategy design |
| `risk` | Risk, assumptions, stress scenarios, and failure modes |
| `portfolio` | Portfolio construction, constraints, and allocation |
| `macro` | Macro, policy, cycle, and cross-asset context |
| `report` | Evidence organization and report presentation |

Independent task-graph nodes execute in parallel. Dependent nodes receive the
outputs of their declared prerequisites. Expert business logic is intentionally
placeholder-only in this iteration; the executor returns explicit placeholder
results without pretending they are real research.

The Manager performs one limited repair call if Ark returns invalid JSON. There
are no uncontrolled model retry loops and no hardcoded keyword workflows.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:ARK_API_KEY = "your-volcano-ark-key"
$env:ARK_MODEL = "your-endpoint-id" # optional
uvicorn backend.main:app --reload
```

The API is available at `http://127.0.0.1:8000`; interactive documentation is
at `/docs`.

## Planning API

`POST /api/plan` returns a validated `ExecutionPlan` without executing it.

```bash
curl -X POST "http://127.0.0.1:8000/api/plan" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"分析机器人行业是否存在投资机会，并设计一个可验证的量化策略\"}"
```

Example response shape:

```json
{
  "goal": "分析机器人行业机会并设计可验证的量化策略",
  "intent": "行业研究与策略设计",
  "complexity": "high",
  "selected_agents": [
    {"agent": "macro", "reason": "评估政策和周期背景"},
    {"agent": "research", "reason": "研究产业机会"},
    {"agent": "quant", "reason": "设计可验证策略"},
    {"agent": "risk", "reason": "审查策略风险"}
  ],
  "steps": [
    {
      "id": "macro_context",
      "agent": "macro",
      "objective": "分析宏观与政策环境",
      "depends_on": [],
      "expected_output": "宏观驱动与约束"
    },
    {
      "id": "industry_research",
      "agent": "research",
      "objective": "分析产业链投资机会",
      "depends_on": [],
      "expected_output": "机会假设与证据"
    },
    {
      "id": "quant_strategy",
      "agent": "quant",
      "objective": "设计可验证的量化策略",
      "depends_on": ["macro_context", "industry_research"],
      "expected_output": "策略规则和验证方案"
    },
    {
      "id": "risk_review",
      "agent": "risk",
      "objective": "审查策略主要风险",
      "depends_on": ["quant_strategy"],
      "expected_output": "风险清单和控制建议"
    }
  ],
  "needs_clarification": false,
  "clarification_question": null
}
```

## Task API

`POST /api/tasks` plans the request, executes dependency-ready steps, records
events and expert results, then asks the Manager for final synthesis.

```bash
curl -X POST "http://127.0.0.1:8000/api/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"检查一个成交量动量策略是否存在主要风险\"}"
```

The response contains:

```json
{
  "plan": {},
  "execution_events": [],
  "expert_results": [],
  "final_answer": "Manager synthesis"
}
```

`POST /api/route` remains available temporarily but is marked deprecated. It is
not used by the v0.2 planning or task APIs.

## PandaData API

Market-data behavior is unchanged. Configure the PandaAI account in the
terminal that starts the backend. The username is the registration phone number
prefixed with `86`.

```powershell
$env:PANDADATA_USERNAME = "8617777777777"
$env:PANDADATA_PASSWORD = "your-pandaai-password"
```

Use `GET /api/pandadata/status` to inspect configuration without exposing
credentials. Fetch stock daily data through `POST /api/market-data`:

```bash
curl -X POST "http://127.0.0.1:8000/api/market-data" \
  -H "Content-Type: application/json" \
  -d "{\"symbols\":[\"000001.SZ\"],\"start_date\":\"20250101\",\"end_date\":\"20250131\",\"fields\":[],\"indicator\":\"000300\",\"st\":true}"
```

## Tests

Ark is mocked in all planning-kernel tests, so automated tests do not spend API
quota.

```powershell
python -m pytest -q tests
```
