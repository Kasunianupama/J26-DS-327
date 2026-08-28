# Dairy Intelligence Research Monorepo

**Machine Learning-Based Prediction of Milk Yield in Dairy Cows in Farming Systems** — an initial decision-support scaffold for the NLDB research context.

## Research components

1. **AI-powered Dairy Intervention Digital Twin (DIDT) & Intervention Optimization Engine**: future prediction, biological simulation, validation, optimisation and intervention recommendations.
2. **Adaptive Emotional & Behavioral Intelligence System**: future modality-adaptive herd behaviour, welfare, perturbation and transfer intelligence.
3. **Explainable AI & Farmer Reasoning Engine (Dual-Layer Digital Agronomist)**: the conversational synthesis layer for evidence, explanations, contextual reasoning and farmer-facing directives.
4. **Dairy Crisis Forecasting & National Risk Engine**: future farm risk, early warnings and National Dairy Risk Index (NDRI).

Member 3 is designed to consume typed outputs from Members 1, 2, and 4. Member 4 operates in parallel to provide farm and network-level forward-risk intelligence. Components communicate through `shared/schemas`, never through one another's internal code.

## Architecture

`React UI → FastAPI integration boundary → independent research services`.

The initial endpoints use deterministic demo responses only. No ML models, LLM calls, vector database, credentials, or NLDB data are included.

## Repository layout

- `frontend/` React + TypeScript + Vite role-aware prototype UI
- `backend/` FastAPI, configuration, database abstraction and API routes
- `components/` independently testable research-component architecture
- `shared/` Pydantic integration contracts
- `data/sample/` tiny synthetic data only
- `tests/`, `docs/`, `scripts/` test, documentation and operational homes

## Setup

Copy `.env.example` to `.env` only for local development. Never commit it.

Backend (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
pytest
uvicorn backend.app.main:app --reload
```

Frontend:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run build
npm run dev
```

The frontend reads `VITE_API_BASE_URL`, defaulting to `http://localhost:8000/api/v1`. FastAPI permits the Vite development origin `http://localhost:5173` via configured CORS.

Optional local PostgreSQL: `docker compose up -d`. Basic tests do not require it.

## Team workflow

Recommended branches: `main`, `develop`, `feature/member1-didt`, `feature/member2-behavioral-intelligence`, `feature/member3-farmer-reasoning`, `feature/member4-crisis-forecasting`, `feature/frontend`, and `feature/integration`.

Keep research logic outside route files and UI code. Keep each component's work independently testable and evolve contracts deliberately.

## Sample-data disclaimer

All included data is fictional, synthetic demo data. It is not NLDB data and does not represent research outcomes.
