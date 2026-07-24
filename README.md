# Arcscrow backend

FastAPI modular monolith for authentication, deals, milestones, evidence, chat,
AI verification, files, notifications and chain reconciliation.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

API docs: `http://localhost:8000/docs`; health:
`http://localhost:8000/api/v1/health`.

For production, use PostgreSQL. Tests use isolated SQLite. The development AI
and Circle wallet adapters are visibly marked simulations and never create fake
chain confirmations.
