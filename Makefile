# pmg-assist pipeline, after "Data Science at the Command Line" ch. 6:
# each OSEMN step is a target, run from the repo root.
#
# Tools are called through the venv's own paths, so a target never picks up a
# system python or ruff by accident (the ghpulse lesson), activated or not.

VENV   := .pmgvenv
PY     := $(VENV)/bin/python
BRONZE := data/bronze
INGEST := PYTHONPATH=ingest $(PY) -m pmg_ingest.bronze --root $(BRONZE)

.PHONY: help venv lint test spec check bronze-status bronze-plan bronze measure

help:   ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

venv:   ## create the venv and install dev requirements
	python3.12 -m venv $(VENV)
	$(PY) -m pip install -r requirements-dev.txt

# ---- code checks (offline; what CI runs)
lint:   ## ruff over the Python code
	$(VENV)/bin/ruff check ingest api

test:   ## offline checks
	$(PY) ingest/tests/test_bronze.py

spec:   ## validate the API contract
	$(PY) -c "from openapi_spec_validator import validate; from openapi_spec_validator.readers import read_from_filename; validate(read_from_filename('docs/api.openapi.yaml')[0]); print('spec valid')"

check: lint test spec   ## all offline checks

# ---- O: obtain (network; needs PMG_INGEST_CONTACT; never run in parallel against PMG)
bronze-status:   ## API counts per year vs local state; writes nothing
	$(INGEST) --status

bronze-plan:     ## what a backfill would fetch; writes nothing
	$(INGEST) --dry-run

bronze:          ## fetch committee-question into data/bronze (~15 min)
	$(INGEST)

# ---- E: explore
measure:         ## measurement queries over bronze
	duckdb < ingest/sql/measure_committee_question.sql
