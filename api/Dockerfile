# pmg-assist API image. Build from the repo root:
#   docker build -f api/Dockerfile -t pmg-assist-api .
# Only the API code and the contract go in (see .dockerignore); bronze data never does.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt

COPY api/pmg_api api/pmg_api
COPY docs/api.openapi.yaml docs/api.openapi.yaml

RUN useradd --system --uid 10001 app
USER 10001

EXPOSE 8077
# 0.0.0.0 inside the container only; the Kubernetes Service decides what is exposed.
CMD ["uvicorn", "pmg_api.main:app", "--app-dir", "api", "--host", "0.0.0.0", "--port", "8077"]
