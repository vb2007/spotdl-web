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
# `>=` bounds fresh at every build. A scheduled CI job (ci.yml) flags when the yt-dlp
# version below falls behind PyPI's latest, and `backend/uv.lock` is tracked so CI can
# also catch requirements.txt drifting from pyproject.toml.
COPY pyproject.toml requirements.txt ./

# Plain pip can't see pyproject.toml's [tool.uv] override-dependencies (needed because
# spotdl hard-pins fastapi/uvicorn for its own unused bundled web UI — see CLAUDE.md v04
# gotchas) — requirements.txt was generated *with* that override already applied via uv,
# so a plain `pip install -r` would work for this step alone, but uv is kept for speed
# and to install this local package itself, below.
RUN pip install --no-cache-dir uv \
    && uv pip install --system --no-cache-dir -r requirements.txt

# v23: yt-dlp floats to latest on every rebuild while everything else stays pinned via
# the lock file above — it's the one dependency whose entire job is chasing a moving
# target (YouTube breaks extraction and yt-dlp ships fixes within days), and pinning it
# is what produced the v23 outage (root-caused this version — see docs/GOTCHAS.md).
# Real-stack repro proved the pin itself wasn't the actual outage cause here (PyPI's
# latest stable was already what was pinned; the real fix was the Deno step below), but
# this stays as standing policy so a *future* extraction break doesn't wait for someone
# to notice and re-run `uv pip compile` by hand. The scheduled CI freshness check
# (ci.yml) is the safety net for when this step can't reach PyPI at build time.
RUN uv pip install --system --no-cache-dir --upgrade yt-dlp

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

# v23: YouTube now gates most (music.youtube.com) extractions behind a PO-token challenge
# that requires a JS runtime to solve. Without this, spotdl.utils.deno.get_local_deno()
# finds nothing, search_and_download() swallows the resulting AudioProviderError
# ("Sign in to confirm you're not a bot") internally and returns a bare `None` output
# path instead of raising -- this was the actual outage, root-caused this version by
# reproducing it against the real stack (see docs/GOTCHAS.md's v23 entry). Baked into the
# image (not a boot-time fetch) so every worker/api process shares one download and
# doesn't race or depend on deno.land being reachable at container start. Must run as
# the `spotdl` user (after USER above) so it lands under this user's own
# get_spotdl_path() rather than root's.
RUN python -m spotdl --download-deno

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
