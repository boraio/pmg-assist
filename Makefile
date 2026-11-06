# pmg-assist pipeline, after "Data Science at the Command Line" ch. 6:
# each OSEMN step is a target, run from the repo root.
#
# Tools are called through the venv's own paths, so a target never picks up a
# system python or ruff by accident (the ghpulse lesson), activated or not.

VENV   := .pmgvenv
PY     := $(VENV)/bin/python
BRONZE := data/bronze
INGEST := PYTHONPATH=ingest $(PY) -m pmg_ingest.bronze --root $(BRONZE)
SILVER := data/silver
# silver's output folder carries silver.VERSION; read it from the code so the two never disagree
SILVER_CQ = $(SILVER)/committee-question/version=$(shell PYTHONPATH=ingest $(PY) -c 'from pmg_ingest.silver import VERSION; print(VERSION)')

.PHONY: help venv lint test spec check api bronze-status bronze-plan bronze measure silver

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
	$(PY) ingest/tests/test_silver.py
	$(PY) -m pytest api/tests -q

spec:   ## validate the API contract
	$(PY) -c "from openapi_spec_validator import validate; from openapi_spec_validator.readers import read_from_filename; validate(read_from_filename('docs/api.openapi.yaml')[0]); print('spec valid')"

check: lint test spec   ## all offline checks

# ---- API (Milestone 0 stub). Port 8077: 8000 is taken on the dev machine.
api:    ## run the API locally on :8077 with reload
	$(VENV)/bin/uvicorn pmg_api.main:app --app-dir api --port 8077 --reload

# ---- O: obtain (network; needs PMG_INGEST_CONTACT; never run in parallel against PMG)
bronze-status:   ## API counts per year vs local state; writes nothing
	$(INGEST) --status

bronze-plan:     ## what a backfill would fetch; writes nothing
	$(INGEST) --dry-run

bronze:          ## fetch committee-question into data/bronze (~15 min)
	$(INGEST)

# ---- S: scrub
silver:          ## bronze committee-question -> silver JSONL + Parquet (ADR 0003)
	PYTHONPATH=ingest $(PY) -m pmg_ingest.silver --bronze-root $(BRONZE) --out $(SILVER)
	duckdb -c "COPY (SELECT * FROM read_json('$(SILVER_CQ)/records.jsonl', format = 'newline_delimited', sample_size = -1, maximum_object_size = 268435456)) TO '$(SILVER_CQ)/records.parquet' (FORMAT parquet, COMPRESSION zstd)"
	duckdb -c "SELECT count(*) AS rows, count(DISTINCT record_id) AS ids, count(*) FILTER (WHERE reply_kind = 'attachment_pointer') AS pointers FROM '$(SILVER_CQ)/records.parquet'"

# ---- E: explore
measure:         ## measurement queries over bronze
	duckdb < ingest/sql/measure_committee_question.sql
