# Setup

Running the systematic trading platform locally.

For what the system *is* and why it is built this way, read `CLAUDE.md`. This
file is only about getting it up.

## Prerequisites

Two supported routes. Docker is fewer steps; the local route is better if you
intend to change code, because you get a REPL and the test suite.

| Route | Needs |
|---|---|
| Docker | Docker Engine 20.10+ **and the Compose V2 plugin** |
| Local | Python 3.11+, Node 20+, PostgreSQL 14+ |

### Compose V2 is required, and its absence reports badly

The compose file uses `profiles:` and `depends_on: condition:`, which are
Compose V2 features. If the plugin is missing you get an error that names the
flag rather than the cause:

```
$ docker compose --profile web up --build
unknown flag: --profile

Usage:  docker [OPTIONS] COMMAND [ARG...]
```

That usage block is `docker`'s own, not Compose's — the CLI never found a
`compose` subcommand to hand the flags to, so it parsed them against the root
command and rejected the first one it did not recognise. The same failure on
`docker compose run --rm …` reports `unknown flag: --rm`. Neither message
mentions Compose, which is what makes it confusing.

Check with:

```bash
docker compose version     # V2 installed -> "Docker Compose version v2.x.x"
                           # missing      -> "docker: 'compose' is not a docker command"
```

To install it:

- **Docker Desktop (macOS/Windows)** — bundled since v3.4. If it is missing,
  Docker Desktop is old; update it.
- **Linux, Docker's apt/dnf repo** — `sudo apt-get install docker-compose-plugin`
- **macOS without Docker Desktop** — `brew install docker-compose`, which installs it
  into `~/.docker/cli-plugins` for you.
- **Anywhere else** — drop the binary in as a CLI plugin. Note the two
  transformations: the release assets use a **lowercase** OS, and `aarch64`
  where macOS's `uname -m` says `arm64`. Passing `uname` output through
  unmodified requests an asset that does not exist.

  ```bash
  mkdir -p ~/.docker/cli-plugins

  OS=$(uname -s | tr '[:upper:]' '[:lower:]')
  ARCH=$(uname -m); [ "$ARCH" = "arm64" ] && ARCH=aarch64

  curl -fSL "https://github.com/docker/compose/releases/latest/download/docker-compose-${OS}-${ARCH}" \
      -o ~/.docker/cli-plugins/docker-compose
  chmod +x ~/.docker/cli-plugins/docker-compose
  docker compose version
  ```

  `-f` is load-bearing. Without it curl treats GitHub's 404 as an ordinary
  response and writes the nine-byte body `Not Found` to the output path; the
  `chmod +x` then succeeds, and you are left with an executable that is not a
  binary. If the download ever looks wrong, `file ~/.docker/cli-plugins/docker-compose`
  should report Mach-O or ELF and the size should be tens of megabytes.

  If the asset name is ever wrong, ask GitHub what it publishes rather than
  guessing:

  ```bash
  curl -fsSL https://api.github.com/repos/docker/compose/releases/latest \
      | grep -o '"name": *"docker-compose-[^"]*"'
  ```

**Do not substitute the old hyphenated `docker-compose` (V1).** It is
end-of-life, and it will not work here for a specific reason: this compose file
has no `version:` key, which V2 reads as "current schema" and V1 reads as the
legacy version-1 format — a format with no `profiles`, no conditional
`depends_on`, and no top-level `volumes`. V1 does not fail cleanly on that; it
misreads the file.

## 1. Configure

```bash
cp .env.example .env
```

Three values are required and have no defaults. A signing key with a fallback
value is a signing key an attacker already knows, so the API will not mint or
accept a session without a real one — `/api/v1/ready` answers 503 and names
what is missing, and every authenticated route refuses until you set them:

```bash
# POSTGRES_PASSWORD — anything; it only has to match itself
python -c "import secrets; print(secrets.token_urlsafe(24))"

# SESSION_SECRET
python -c "import secrets; print(secrets.token_urlsafe(48))"

# ADMIN_PASSWORD_HASH — your operator login, bcrypt-hashed
python -c "import bcrypt; print(bcrypt.hashpw(b'your-password', bcrypt.gensalt()).decode())"
```

### Single-quote every value in `.env`

A bcrypt hash starts `$2b$12$…`, and `$2`, `$1` and `$b` are shell variable
references. Any tooling that sources `.env` through a shell — a heredoc,
`set -a; . ./.env`, some editor plugins — will expand them to empty strings and
silently truncate the hash. The failure surfaces much later as "wrong password"
with a correct password, which points nowhere near the real cause.

```bash
ADMIN_PASSWORD_HASH='$2b$12$abcdefg...'   # correct
ADMIN_PASSWORD_HASH=$2b$12$abcdefg...     # becomes "b12abcdefg..." in a shell
```

Docker Compose's own `env_file` parser does not expand `$`, so quoting is
belt-and-braces there — but quote anyway, because the same file gets sourced by
hand sooner or later.

## 2. Run

### With Docker

```bash
docker compose --profile web up --build      # db + api + worker + UI
```

In a second terminal, once Postgres reports healthy:

```bash
docker compose run --rm api python -m src.db.migrate_cli
```

Migrations are forward-only numbered SQL under `migrations/`, applied inside a
transaction with a stored checksum. A fresh database needs this once; it is
idempotent, so re-running it is safe.

`docker compose up --build` **without** `--profile web` gives you db + api +
worker only. That is the real deployment shape — the frontend goes to Vercel,
because a Next.js server has no business holding a trading loop. The `web`
service exists so the whole stack comes up with one command on a laptop, and it
runs `next dev` rather than a production build.

### Without Docker

Fewer moving parts if you already have Postgres, and it is the better choice if
you intend to change code — you get the test suite and a REPL.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

createdb trader
export DATABASE_URL=postgresql://localhost:5432/trader
.venv/bin/python -m src.db.migrate_cli

.venv/bin/uvicorn src.api.main:app --reload    # terminal 1
.venv/bin/python -m src.worker.main            # terminal 2
cd web && npm install && npm run dev           # terminal 3
```

On macOS with Homebrew Postgres, start it first and note that the superuser is
your own account rather than `postgres`, so the DSN above needs no credentials:

```bash
brew services start postgresql@16     # match your installed version
createdb trader                       # uses $(whoami) as owner
```

The API still needs `SESSION_SECRET` and `ADMIN_PASSWORD_HASH` in the
environment. `.env` is read by docker-compose, not by a bare `uvicorn`, so
either export them or source the file — and if you source it, see the quoting
warning above.

`requirements-dev.txt` is the development set. `requirements.txt` is what
deploys — the same list minus test and research tooling.

The API and worker are separate processes on purpose. A backtest is CPU-bound
pandas work; running it inside the API process would block the event loop and
stall every other request, including the one an operator is using to stop
trading.

## 3. Verify

```bash
curl localhost:8000/api/v1/health      # {"status":"ok","version":"..."}
```

Then open `http://localhost:3000` and log in with the password you hashed.

`CORS_ORIGINS` must match what the browser actually uses. `localhost` and
`127.0.0.1` are different origins to a browser, and mixing them produces a CORS
failure that looks like a broken login.

## 4. Your first backtest

A fresh database is empty; there is nothing to look at until you run something.

1. Log in, pick `asset_class_trend_following`
2. Set the data source to **synthetic**
3. Adjust `sma_period` if you like, and hit run

Use synthetic first even if you have working network. `SyntheticSource` labels
itself as synthetic in every output it touches, so what you are checking is that
the honesty controls fire: the tearsheet must show the synthetic-data banner,
the Sharpe standard error, and the annualisation basis. A number rendered
without those is a number that misleads, and seeing them appear is the point of
the first run.

The `yfinance` path is implemented but has never been exercised — the
environment this was developed in blocks every equity data host. It may work
first try on your machine or may need a version bump. Nothing in this repository
has ever been measured against real equity prices; treat any figure you see as a
test of the machinery, not of a strategy.

## 5. Deploying

The split is locked: **frontend on Vercel, backend on its own host.** A Next.js
server cannot hold a trading loop — a backtest is CPU-bound pandas work, and a
serverless function that sleeps between market sessions is not a worker.

### What is deployed right now

Recorded here because a running system whose address lives only in a dashboard
is a system nobody can check.

| Piece | Where | Plan |
|---|---|---|
| UI | https://trader-ui-black.vercel.app | Vercel, free |
| API | https://trader-api-515t.onrender.com | Render web service, free |
| Database | Render Postgres `trader-db`, Oregon | free, **expires 2026-09-02** |
| Job scheduler | `.github/workflows/drain.yml`, every 10 minutes | GitHub Actions |

Three consequences of the free tiers, each of which changes what the system can
be trusted to do:

- **There is no worker.** Render has no free background-worker tier, so
  `trader-worker` from `render.yaml` does not exist. `SERVERLESS_DRAIN_ENABLED`
  lets the API run `backtest` and `walkforward` jobs itself and the workflow
  above asks it to, so research works. **Live trading does not**, and the System
  page says so: it reports no worker alive, which is true and is the right thing
  for it to report. A live deployment needs the paid worker.
- **The database expires after 30 days**, and it takes `daily_marks` with it —
  the table both halting limits are measured against. Upgrade it before then or
  the equity history goes, silently.
- **The API sleeps after 15 minutes idle** and takes about a minute to answer
  the request that wakes it. The ten-minute drain keeps it awake in practice.

Upgrading is one action: add a card to the Render account and deploy
`render.yaml` as a Blueprint, which brings the paid database, the paid API and
the worker in one step. The workflow above becomes redundant then; the worker
claims jobs faster than a ten-minute schedule can.

### Everything on Vercel — two projects from one repository

The whole research lab runs on Vercel: the Next.js UI and the FastAPI control
plane, as two projects pointed at the same repository with different root
directories. Both use Vercel's own detection rather than a hand-written build,
because a zero-config project is one that still works after an upgrade.

The **live trading path does not run here.** It needs a process that outlives a
request — a scheduler that wakes at the close, and a worker holding the only
route to a broker. Serverless has nowhere to put one. Use `render.yaml` below
when you get there. What deploys here is the part that is actually useful
today: run backtests, read tearsheets, work the kill switch.

**Project 1 — the API.** Import the repo; leave **Root Directory** at the
repository root. `vercel.json` and `api/index.py` do the rest: the Python
runtime installs `requirements.txt` (the deployable set, ~190MB against a
250MB limit) and serves the same FastAPI app uvicorn does.

For the database, Vercel's marketplace offers Neon, which sets `DATABASE_URL`
on the project for you. Paste one in from anywhere else and it works too:
connection strings from managed providers often carry `channel_binding=require`,
which asyncpg cannot honour and Postgres rejects outright, so it is stripped
with a warning rather than left to fail at the first request.

```bash
DATABASE_URL=...                          # any managed Postgres
SESSION_SECRET=...                        # 32+ chars
ADMIN_PASSWORD_HASH=...                   # bcrypt
CORS_ORIGINS=https://<ui>.vercel.app      # exact origin, no trailing slash
SESSION_COOKIE_SAMESITE=none              # required; see below
SERVERLESS_DRAIN_ENABLED=true             # required; see below
CRON_SECRET=...                           # any long random string
DB_POOL_MAX_SIZE=3                        # required; see below
LIVE_TRADING_ENABLED=false
ALPACA_ALLOW_LIVE=false
```

**Project 2 — the UI.** Import the same repo, set **Root Directory to `web`**,
and set `NEXT_PUBLIC_API_BASE` to project 1's URL. The default root is the
repository root, where there is no `package.json`, and the build then fails
with a framework-detection error that never mentions the root directory.

The two need each other's URLs, so deploy the API first, then the UI, then go
back and set `CORS_ORIGINS`. `NEXT_PUBLIC_*` is inlined at **build** time —
changing it in the dashboard without redeploying does nothing.

Apply migrations once against the database:
`DATABASE_URL=... python -m src.db.migrate_cli` from a checkout.

#### The two settings that are not optional

`SESSION_COOKIE_SAMESITE=none`. The two projects are on different hosts, so the
session cookie is cross-site, and a browser will not attach a `Lax` one. Leave
it at the default and login returns 200 while every call after it returns 401 —
which reads on screen as a correct password being rejected.

`SERVERLESS_DRAIN_ENABLED=true`. There is no worker, so nothing would ever run
a queued backtest; it would sit at "waiting for a worker" indefinitely. With
this set, `POST /api/v1/system/drain` runs queued **research** jobs in the
request — the UI calls it while polling a queued run, and `vercel.json`
schedules a daily sweep. It is off by default and must stay off wherever a
worker exists: a backtest is CPU-bound pandas work, and running one inside a
request handler on a long-lived server stalls every other request on that event
loop, including the one an operator is using to hit the kill switch.

Trading jobs are never drainable. "The worker is the only process that places
an order" is what makes the kill-switch check and the three live gates
meaningful, and `test_drain_boundary.py` fails the build if a trading kind is
ever added to that set.

`DB_POOL_MAX_SIZE=3`. The default of 10 assumes one long-lived process holding
one pool. On a serverless host every cold start builds its own and none of them
share, so ten warm instances mean up to a hundred connections against a free
tier that allows a small fraction of that. The failure is not a slow API, it is
`too many clients already`, and it arrives exactly when traffic picks up.
Prefer the provider's pooled endpoint as well — Neon and Supabase both publish
one, and it multiplexes properly rather than leaving each instance to guess.

### The whole system in one action (Render Blueprint)

`render.yaml` declares everything — Postgres, the API, the worker, **and the
UI** — with the cross-references (`NEXT_PUBLIC_API_BASE`, `CORS_ORIGINS`) wired
to whatever hostnames Render actually assigns. Deploying it is:

1. **Render dashboard → New → Blueprint →** select this repository.
2. Type one value when prompted: `ADMIN_PASSWORD_HASH` (bcrypt; the generator
   is below). `SESSION_SECRET` is generated server-side and never displayed.
3. Apply. Migrations run automatically before the API takes traffic
   (`preDeployCommand`), so there is nothing to run by hand.

The API and worker use paid instances deliberately — a free web service spins
down, which delays the kill switch behind a cold start, and free Postgres
expires after 90 days and takes `daily_marks` (the risk gate's memory) with
it. The UI is free tier: a spun-down UI costs a wait, not a control.

### Backend by hand (Fly / Railway / anything with a Docker runtime)

`Dockerfile` builds one image; run it twice with different commands — the API
(`uvicorn src.api.main:app`) and the worker (`python -m src.worker.main`). The
worker is not optional: without it, backtests queue forever and no mark is ever
written, which silently disarms both halting limits.

Set on the API:

```bash
DATABASE_URL=...                              # managed Postgres
SESSION_SECRET=...                            # 32+ chars
ADMIN_PASSWORD_HASH=...                       # bcrypt
CORS_ORIGINS=https://your-app.vercel.app      # exact origin, no trailing slash
SESSION_COOKIE_SAMESITE=none                  # required: see below
LIVE_TRADING_ENABLED=false
ALPACA_ALLOW_LIVE=false
```

Then apply migrations once against the deployed database:
`python -m src.db.migrate_cli`.

**`SESSION_COOKIE_SAMESITE=none` is required in this topology and easy to miss.**
`vercel.app` and your API's host are different *sites*, so the session cookie is
cross-site, and a browser will not attach a `Lax` cookie to a cross-site fetch.
Leave it at `lax` and login returns 200 while every call after it returns 401 —
which presents as a correct password being rejected, with nothing in the server
log looking wrong. `none` implies `Secure`, which the API sets for you.

### Pointing a deployed frontend at a local backend

Workable for a look around, with caveats worth knowing before you spend time on
it. Set `NEXT_PUBLIC_API_BASE=http://localhost:8000` and on the local API set
`CORS_ORIGINS` to the Vercel origin plus `SESSION_COOKIE_SAMESITE=none`.
Chromium and Firefox treat `http://localhost` as a trustworthy origin and allow
it from an HTTPS page; Safari is stricter and may refuse. Running the frontend
locally too is less trouble than debugging that.

## 6. Tests

```bash
.venv/bin/pytest tests/unit -q                  # no database needed

TEST_DATABASE_URL=postgresql://localhost/trader_test \
    .venv/bin/pytest tests/ -q                  # adds the integration suite

.venv/bin/pytest tests/unit/test_parity.py -q   # the important one
.venv/bin/ruff check src/ tests/
```

`test_parity.py` asserts the backtest and live paths emit byte-identical order
intents from identical inputs. If it fails, the backtest has stopped predicting
the live system, which is worse than whatever bug the change was fixing. Run it
before and after touching `src/core/`, `src/engine/` or `src/execution/`.

The browser journey needs the whole stack running and so is not in CI:

```bash
.venv/bin/python tests/e2e/test_browser_journey.py
```

## 7. Trading is off, and stays off

Nothing here can reach a real venue, by construction rather than by
configuration you might forget:

- The database kill switch defaults to halted and **fails closed** — a missing
  row, an unreadable value or any database error all return "do not trade".
- Reaching a live Alpaca endpoint takes **three independent** conditions: the
  deployment row's `mode=live`, `LIVE_TRADING_ENABLED`, and `ALPACA_ALLOW_LIVE`.
  Two environment variables rather than one is deliberate; the broker factory
  once derived the third from the second, which quietly reduced three gates to
  two while every test still passed.
- Alpaca has never been contacted from this codebase. `AlpacaBroker` is tested
  against a fake server modelling the documented contract.

Leave `LIVE_TRADING_ENABLED` and `ALPACA_ALLOW_LIVE` as `false`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `unknown flag: --profile`, with `docker`'s root usage | Compose V2 plugin not installed — see above |
| Correct password rejected at login | `ADMIN_PASSWORD_HASH` unquoted in `.env`; the shell ate `$2b$12` |
| Same, but only when reaching the API over a LAN IP | The session cookie is `Secure` whenever `CORS_ORIGINS` is set. Browsers treat `localhost` as a secure context and accept it over plain HTTP; `http://192.168.x.x` is not, so the cookie is discarded and every call after login is anonymous. Use localhost, or terminate TLS |
| Login returns 503, or every authenticated route does | `SESSION_SECRET` or `ADMIN_PASSWORD_HASH` empty. There is no default, on purpose. `curl .../api/v1/ready` names exactly which |
| `SESSION_SECRET must be at least 32 characters` | Exactly that. Use the generator above rather than typing one |
| Login succeeds, every subsequent call fails in the browser | `CORS_ORIGINS` does not match the origin in the address bar (`localhost` ≠ `127.0.0.1`) |
| `relation "…" does not exist` | Migrations not applied — `python -m src.db.migrate_cli` |
| Backtest queues but never finishes | The worker is not running. It is a separate process from the API |
| Backtest fails fetching prices | Expected on `yfinance`; use the synthetic source |
| `MigrationError: checksum mismatch` | An applied migration was edited. Never edit one — write a new numbered file |
| Port 5432 already in use | A local Postgres is running. Change the host-side port in `docker-compose.yml` |
