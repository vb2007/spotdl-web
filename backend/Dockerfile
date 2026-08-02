FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies before source (v12) — a source-only edit now reuses this cached layer
# instead of re-resolving/re-downloading the full tree (incl. spotdl/yt-dlp) on every
# build, which matters once builds happen on the remote Debian host rather than a fast
# local machine. requirements.txt is a committed lock file
# (`uv pip compile pyproject.toml -o requirements.txt`, re-run after any pyproject.toml
# dependency change — see CLAUDE.md) rather than resolving pyproject.toml's floating
# `>=` bounds fresh at every build — this project has no dependency-freshness check in
# CI, so an unpinned rebuild months from now could otherwise silently install a
# different yt-dlp/spotdl than whatever was last actually tested.
COPY pyproject.toml requirements.txt ./

# Plain pip can't see pyproject.toml's [tool.uv] override-dependencies (needed because
# spotdl hard-pins fastapi/uvicorn for its own unused bundled web UI — see CLAUDE.md v04
# gotchas) — requirements.txt was generated *with* that override already applied via uv,
# so a plain `pip install -r` would work for this step alone, but uv is kept for speed
# and to install this local package itself, below.
RUN pip install --no-cache-dir uv \
    && uv pip install --system --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY logging.json ./

# --no-deps: dependencies are already satisfied by the layer above; this only installs
# the local `app` package itself on top of it.
RUN uv pip install --system --no-cache-dir --no-deps .

# Non-root (v12): downloaded files land on a host bind mount in production
# (docker-compose.prod.yml's DOWNLOADS_DIR) — running as root would write those files
# root-owned on the host. Fixed uid/gid default to 1000, the conventional first non-root
# user id on Debian/most Linux distros (matches this project's own dev machine and is
# what docs/DEPLOYMENT.md tells the Debian host's deploy user to `chown` the downloads
# directory to) — override via --build-arg if a given host's deploy user differs.
#
# --create-home is required, not optional, despite this being a service account with no
# interactive shell: `import spotdl` (transitively, e.g. via app/services/expansion.py)
# runs spotdl.utils.config module-level code that unconditionally
# os.makedirs()-creates a `~/.spotdl` cache/config directory at *import time* — every
# process that ever imports spotdl (api, both workers, beat, since celery_app.py imports
# every task module at startup) crashes on the very first import with a bare
# `PermissionError: [Errno 13] Permission denied: '/home/spotdl'` if that directory
# doesn't exist and isn't writable. Caught by actually starting every one of these
# services locally after switching to non-root, not assumed.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "$APP_GID" spotdl \
    && useradd --uid "$APP_UID" --gid spotdl --create-home --shell /usr/sbin/nologin spotdl \
    && chown -R spotdl:spotdl /app
USER spotdl

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
