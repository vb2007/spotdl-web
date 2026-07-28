FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Plain pip can't see pyproject.toml's [tool.uv] override-dependencies (needed because
# spotdl hard-pins fastapi/uvicorn for its own unused bundled web UI — see CLAUDE.md v04
# gotchas), so this needs uv's resolver, not pip, to install correctly.
RUN pip install --no-cache-dir uv \
    && uv pip install --system --no-cache-dir .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
