PYTHON ?= python3

.PHONY: backend frontend test

backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && $(PYTHON) -m pytest

