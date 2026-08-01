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
- **Anywhere else** — drop the binary in as a CLI plugin:

  ```bash
  mkdir -p ~/.docker/cli-plugins
  curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
      -o ~/.docker/cli-plugins/docker-compose
  chmod +x ~/.docker/cli-plugins/docker-compose
  docker compose version
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
value is a signing key an attacker already knows, so the API refuses to start
without them rather than inventing one:

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

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

createdb trader
export DATABASE_URL=postgresql://localhost:5432/trader
.venv/bin/python -m src.db.migrate_cli

.venv/bin/uvicorn src.api.main:app --reload    # terminal 1
.venv/bin/python -m src.worker.main            # terminal 2
cd web && npm install && npm run dev           # terminal 3
```

`requirements.txt` is the development set. `requirements-engine.txt` is what
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

## 5. Tests

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

## 6. Trading is off, and stays off

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
| API exits at startup complaining about a missing value | `SESSION_SECRET` or `ADMIN_PASSWORD_HASH` empty. There is no default, on purpose |
| `SESSION_SECRET must be at least 32 characters` | Exactly that. Use the generator above rather than typing one |
| Login succeeds, every subsequent call fails in the browser | `CORS_ORIGINS` does not match the origin in the address bar (`localhost` ≠ `127.0.0.1`) |
| `relation "…" does not exist` | Migrations not applied — `python -m src.db.migrate_cli` |
| Backtest queues but never finishes | The worker is not running. It is a separate process from the API |
| Backtest fails fetching prices | Expected on `yfinance`; use the synthetic source |
| `MigrationError: checksum mismatch` | An applied migration was edited. Never edit one — write a new numbered file |
| Port 5432 already in use | A local Postgres is running. Change the host-side port in `docker-compose.yml` |
