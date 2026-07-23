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
adapter in `frontend/presentation/`. The default **看得懂版** reads
`response.aggregation` first, displays `direct_answer`, and dispatches only the
returned `content_blocks` through a block renderer map. It creates no fixed
agent sections or empty placeholder cards. Legacy demo responses receive a
small compatibility adaptation, but live research conclusions are generated
only by the server-side Result Aggregator.

The **专业证据** view preserves the Manager-created expert DAG, selection
reasons, structured expert results, raw `validation_status`, skill and tool
provenance, Result Aggregator output, and complete execution-event fields. Potential
credentials, internal paths, prompts, stack traces, and bulk raw market data
are filtered from displayed JSON. Demo values are always labelled `DEMO DATA`
and are never presented as live research evidence.
