---
name: neon-postgres
description: >-
  Guides and best practices for working with Lakebase Postgres, the database
  behind Neon. Covers setup, connection methods and drivers, pooled vs direct
  connections, branching, autoscaling, scale-to-zero, instant restore, read
  replicas, connection pooling, IP allow lists, and logical replication.
  Use when users ask about "Lakebase Postgres", "Neon setup", "connect to Neon",
  "Neon project", "DATABASE_URL", "serverless Postgres", "Neon CLI", "neon", "Neon MCP",
  "Neon Auth", "@neondatabase/serverless", "@neondatabase/neon-js",
  "scale to zero", "Neon autoscaling", "Neon read replica", or
  "Neon connection pooling".
metadata:
  parent: neon
---

**FIRST**: Use the parent `neon` skill for a Neon overview, getting started with Neon, Neon development best practices, and more.

If the `neon` skill is not installed, fetch it from https://neon.com/docs/ai/skills/neon/SKILL.md or install it with:

```bash
npx skills add neondatabase/agent-skills --skill neon
```

# Lakebase Postgres

> **Locally amended.** Installed from
> [`neondatabase/agent-skills`](https://github.com/neondatabase/agent-skills) and since edited for
> this repository, so it no longer matches the `computedHash` in `skills-lock.json`. That mismatch
> is deliberate. Do not run a blanket `skills update` over it; see "Updating Skills" in the parent
> `neon` skill.

Lakebase Postgres is the database at the core of Neon. It runs on the lakebase architecture — OLTP built directly on cloud object storage — which decouples storage from compute to offer autoscaling, branching, instant restore, and scale-to-zero. It's fully compatible with Postgres and works with any language, framework, or ORM that supports Postgres.

It is the same database whether you reach it through Neon or through Databricks; this skill covers the Neon access path.

## Setup Flow

### 1. Select the organization and project

Use the CLI (default) or MCP server to list organizations and projects. Let the user select an existing project or create a new one. Check the `.neon` file for an existing linked project or branch.

### 2. Get the connection string

Use the CLI (default), `neon env pull`, or the MCP server to get the connection string. Store it in `.env` as `DATABASE_URL`. Read the file first before modifying it, to avoid overwriting existing values.

#### When to use pooled vs direct connections

| Use case                                 | Connection type  |
| ---------------------------------------- | ---------------- |
| Web applications, serverless functions   | Pooled (-pooler) |
| Schema migrations                        | Direct           |
| pg_dump / pg_restore                     | Direct           |
| Logical replication                      | Direct           |
| Long-running analytics with temp tables  | Direct           |
| Admin tasks needing SET or session state | Direct           |
| LISTEN / NOTIFY                          | Direct           |

### 3. Pick the connection method and driver

**The project's existing migration authority wins.** Before recommending an ORM, establish whether
the project already has one. A repository with numbered SQL migrations, an Alembic tree, a Rails
`db/migrate` directory or anything equivalent has already chosen, and adding a second tool that
also owns the schema does not add convenience, it adds a way for two ledgers to disagree.

In *this* repository the authority is `src/db/migrate.py`: numbered SQL files in `migrations/`,
applied transactionally, recorded in `schema_migrations` with a checksum that refuses an edited
migration. Do not introduce Drizzle, or any other ORM-managed schema, alongside it. Schema changes
here are a new numbered `.sql` file applied by `python -m src.db.migrate_cli`, and the driver is
`asyncpg` through the pool in `src/db/`. The recommendations below apply to greenfield JavaScript
and TypeScript projects that have no established migration authority.

For a genuinely greenfield project, pairing Neon with an ORM such as **Drizzle** does give you
schema management and migrations cheaply. Refer to the connection methods guide to pick the correct
driver based on how the runtime treats your code: https://neon.com/docs/connect/choose-connection.md.

Recommendations for a greenfield JavaScript or TypeScript project:

- Drizzle as ORM (see https://neon.com/docs/guides/drizzle.md)
- On Vercel, use `node-postgres` (`npm install pg`) with Vercel Fluid compute and `import { attachDatabasePool } from "@vercel/functions";`
- On Cloudflare, use `node-postgres` with Cloudflare Hyperdrive
- On Neon Functions, use `node-postgres`, as the functions are long-running and reuse the pool across requests.
- Use the `@neondatabase/serverless` driver for serverless and edge environments (for example, when using Netlify) — HTTP transport for one-shot queries, WebSocket for transaction support. Link: https://neon.com/docs/serverless/serverless-driver.md

### 4. Set up the schema

Manage schemas and migrations as code. Avoid running ad hoc schema migrations against your database, since they're hard to manage.

**Exactly one tool may own the schema.** Whichever it is, everything goes through it: no ad hoc
`ALTER TABLE` against a branch, no second generator writing migrations the first one cannot see.
In this repository that tool is `src/db/migrate.py` and the migrations are the numbered SQL files
in `migrations/`, which are never edited once applied because the runner verifies their checksums.
In a greenfield project using Drizzle, it is Drizzle, and the same exclusivity applies.

Note also the pooled-versus-direct table above: run migrations over a **direct** connection, not
the `-pooler` endpoint.

## Branching

Use this when the user is planning isolated environments, schema migration testing, preview deployments, or branch lifecycle automation.

Key points:

- Branches are instant, copy-on-write clones (no full data copy).
- Each branch has its own compute endpoint.
- Use the neon CLI or MCP server to create, inspect, and compare branches.

Link: https://neon.com/docs/introduction/branching.md

For detailed branch creation workflows (normal vs schema-only branches, reset-from-parent, CLI/MCP selection), use the `neon-postgres-branches` skill. If it isn't installed, fetch it from https://neon.com/docs/ai/skills/neon-postgres-branches/SKILL.md or install it with:

```bash
npx skills add neondatabase/agent-skills --skill neon-postgres-branches
```

## Autoscaling

Use this when the user needs compute to scale automatically with workload and wants guidance on CU sizing and runtime behavior.

Link: https://neon.com/docs/introduction/autoscaling.md

## Scale to Zero

Use this when optimizing idle costs and discussing suspend/resume behavior, including cold-start trade-offs.

Key points:

- Idle computes suspend automatically after a default of 5 minutes; the timeout is configurable, and suspension can only be disabled on the Launch and Scale plans.
- First query after suspend typically has a cold-start penalty (around hundreds of ms)
- Storage remains active while compute is suspended.

Link: https://neon.com/docs/introduction/scale-to-zero.md

## Instant Restore

Use this when the user needs point-in-time recovery or wants to restore data state without traditional backup restore workflows.

Key points:

- History windows for instant restore depend on plan limits.
- Users can create branches from historical points-in-time.
- Time Travel queries can be used for historical inspection workflows.

Link: https://neon.com/docs/introduction/branch-restore.md

## Read Replicas

Use this for read-heavy workloads where the user needs dedicated read-only compute without duplicating storage.

Key points:

- Replicas are read-only compute endpoints sharing the same storage.
- Creation is fast and scaling is independent from primary compute.
- Typical use cases: analytics, reporting, and read-heavy APIs.

Link: https://neon.com/docs/introduction/read-replicas.md

## Connection Pooling

Use this when the user is in serverless or high-concurrency environments and needs safe, scalable Postgres connection management.

Key points:

- Neon pooling uses PgBouncer.
- Add `-pooler` to endpoint hostnames to use pooled connections.
- Pooling is especially important in serverless runtimes with bursty concurrency.

Link: https://neon.com/docs/connect/connection-pooling.md

## IP Allow Lists

Use this when the user needs to restrict database access by trusted networks, IPs, or CIDR ranges.

Link: https://neon.com/docs/introduction/ip-allow.md

## Logical Replication

Use this when integrating CDC pipelines, external Postgres sync, or replication-based data movement.

Key points:

- Neon supports native logical replication workflows.
- Useful for replicating to/from external Postgres systems.

Link: https://neon.com/docs/guides/logical-replication-guide.md
