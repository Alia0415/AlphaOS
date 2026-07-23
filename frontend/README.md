# AlphaOS Demo Frontend

The demo console is a zero-build-dependency static frontend served directly by
FastAPI.

```powershell
uvicorn backend.main:app --reload
```

Open `http://127.0.0.1:8000/`.

The console intentionally separates two execution paths:

- **Demo mode** uses clearly labelled local example responses. It is suitable
  for a reliable product walkthrough and does not call Ark or PandaData.
- **Live API mode** posts the current prompt to `/api/tasks`. It requires
  `ARK_API_KEY`; market-data tasks also require PandaData credentials.

Both modes pass the same `TaskExecutionResponse` through the presentation
adapter in `frontend/presentation/`. The default **看得懂版** derives its
headline, key points, evidence level, missing evidence, research-only next
steps, risks, and progress from structured expert results. It never treats a
calculation as validation.

The **专业证据** view preserves the Manager-created expert DAG, selection
reasons, structured expert results, raw `validation_status`, skill and tool
provenance, Manager synthesis, and complete execution-event fields. Potential
credentials, internal paths, prompts, stack traces, and bulk raw market data
are filtered from displayed JSON. Demo values are always labelled `DEMO DATA`
and are never presented as live research evidence.
