# AlphaOS

**AlphaOS: Autonomous AI Quant Research Organization**

AlphaOS is an autonomous multi-agent AI quant research organization for AdventureX 2026.

## Core idea

A team of AI financial experts collabor to complete research tasks.

## Agents

- Intent Router Agent
- Research Agent
- Quant Agent
- Risk Agent
- Investment Manager Agent

## Technology

- DeepSeek via Volcano Ark
- A2A Agent Protocol
- QuantSkills
- FastAPI
- React

## PandaData API

Install dependencies and configure the PandaAI account in the terminal that
starts the backend. The username is the registration phone number prefixed
with `86`; credentials are read only from environment variables.

```powershell
pip install -r requirements.txt
$env:PANDADATA_USERNAME = "8617777777777"
$env:PANDADATA_PASSWORD = "your-pandaai-password"
uvicorn backend.main:app --reload
```

Use `GET /api/pandadata/status` to inspect configuration without exposing
credentials. Fetch stock daily data through `POST /api/market-data`:

```json
{
  "symbols": ["000001.SZ"],
  "start_date": "20250101",
  "end_date": "20250131",
  "fields": [],
  "indicator": "000300",
  "st": true
}
```
