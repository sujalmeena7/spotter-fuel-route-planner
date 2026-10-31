.PHONY: setup load run test bench lint

PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff

setup:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt
	$(PYTHON) manage.py migrate

load:
	$(PYTHON) manage.py load_stations

run:
	$(PYTHON) manage.py runserver 0.0.0.0:8000

test:
	$(PYTEST) -v

bench:
	$(PYTHON) manage.py benchmark_routes --mock

lint:
	$(RUFF) check .
	$(RUFF) format --check .
