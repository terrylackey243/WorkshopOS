# WorkshopOS Architecture

Ground-zero rebuild (see `/home/terry/.claude/plans/sleepy-wandering-nest.md`
for the full decision record). This document covers system shape, data
model, and deployment topology as actually built in Milestone 1.

## System diagram

```
                         ┌─────────────────────────┐
                         │   Caddy + Cloudflared    │   (applied separately,
                         │  (homelab reverse proxy) │    not part of this repo)
                         └────────────┬─────────────┘
                                      │  web network
                                      ▼
                         ┌─────────────────────────┐
                         │   workshopos-frontend    │
                         │  nginx:1.27-alpine       │
                         │  serves built React SPA  │
                         │  proxies /api/, /health  │
                         └────────────┬─────────────┘
                     apps network     │  workshopos network
                                      ▼
                         ┌─────────────────────────┐
                         │      workshopos-api      │
                         │  FastAPI + uvicorn       │
                         │  :8000                   │
                         └───┬─────────────────┬────┘
                              │                 │
                 workshopos   │                 │  enqueues jobs
                 network      ▼                 ▼
                ┌───────────────────┐  ┌─────────────────────┐
                │ workshopos-postgres│  │   workshopos-redis   │
                │  postgres:16       │  │   redis:7 (broker)   │
                └───────────────────┘  └───────────┬───────────┘
                                                     │
                                                     ▼
                                        ┌─────────────────────────┐
                                        │    workshopos-worker     │
                                        │  Dramatiq actors         │
                                        │  (geometry generation,   │
                                        │   M2+)                   │
                                        └─────────────────────────┘

    workshopos-migrate: one-shot container, `alembic upgrade head`, exits 0,
    gates api/worker startup via depends_on: service_completed_successfully.
```

`apps` and `web` are external Docker networks shared across this homelab's
apps (see `Server Layout` memory doc); `workshopos` is a private network
created by this compose file for postgres/redis/migrate/api/worker/frontend
to talk to each other without being reachable from other apps.

## The geometry-off-request-thread rule

**Geometry generation must never run synchronously inside an API request
handler.** `workshop_geometry` builds meshes with `trimesh` + `manifold3d`
boolean ops, which are CPU-bound and can take real wall-clock time (fraction
of a second to multiple seconds depending on geometry complexity) — long
enough to block the async event loop and starve every other request on that
worker. This is carried over verbatim from the old architecture doc's
explicit rule, restated here because M2 will need to honor it: any endpoint
that produces label STL output must enqueue a Dramatiq actor and return
immediately (e.g. `Design.status = "queued"`), never call
`workshop_geometry.generate_label()` inline. `app/workers/tasks.py` currently
has only a placeholder `ping` actor — the real geometry actor is M2 work,
once `Design` gets a router.

## Data model summary

Tenancy tree: `Organization` → `Shop` → `Toolbox` → `Drawer`, with FKs
cascading down (`ondelete="CASCADE"`). `User` has no org FK; org membership
is many-to-many via `Membership` (role: `owner|admin|member`).

- **Plan** — `free` (1 shop / 1 toolbox / 5 drawers / 1 user) and `pro`
  (unlimited, all four columns NULL) are seeded by migration `0001`.
  `Organization.plan_id` defaults to `free`.
- **Shop / Toolbox / Drawer** — physical tenancy tree. `Drawer` is a
  *physical instance* (toolbox_id, position_label, notes); its dimensions
  come from a `DrawerProfile` it references, not columns on `Drawer` itself.
  This is a deliberate split from the old schema, which conflated preset
  dimensions with physical instance identity (`toolbox_name`/`drawer_number`
  living directly on `DrawerProfile`).
- **Tool** — org-scoped inventory row, optionally placed in a `Drawer`
  (`drawer_id` nullable = unplaced).
- **5 profile/preset types** (`PrinterProfile`, `MagnetProfile`,
  `MaterialProfile`, `DrawerProfile`, `LabelStyleProfile`) — all share the
  `ProfileBase` mixin shape: UUID pk, `organization_id`, `name`,
  `is_default` (exactly one `is_default=true` row per org per type,
  enforced in the router layer via `UPDATE ... SET is_default=false` before
  flipping a new one on). `LabelStyleProfile` mirrors
  `workshop_geometry.label_engine.LabelParameters` /
  `MagnetPocketParameters`'s layout half directly — column-for-column, so a
  future geometry actor can construct a `LabelParameters` from one row with
  no translation layer.
- **Design** — schema + migration only in M1, no router yet (M2 work).
  `parameters_json` stores a full `LabelParameters` snapshot;
  `engine_version`/`content_hash` map directly onto
  `generation_manifest()["engine_version"]` and
  `parameter_checksum_sha256` from the geometry engine — no new hashing
  scheme was invented.
- **Gridfinity stubs** (`InsertDesign`, `DrawerLayout`, `InsertPlacement`) —
  schema-only, zero logic. Reserve room for the (currently unspecified)
  Gridfinity-style bin generation / auto-layout / packing feature, which has
  no prior code or spec anywhere and is out of scope for M1.

## Auth & tenant isolation

`POST /auth/register` creates `Organization` + unique `slug` + free `Plan` +
`User` + owner `Membership` in a single transaction and returns a JWT.
`POST /auth/login` verifies an argon2 password hash and issues a JWT.

Every organization-scoped route lives under
`/organizations/{organization_id}/...` and depends on
`get_current_membership`, which queries for a real `Membership` row joining
the authenticated user (from the JWT, via `get_current_user`) to that path's
`organization_id`. If no such row exists, the request 403s before touching
any org data.

This directly fixes a real vulnerability in `Workshop-Designer`: its
`routers/profiles.py` took `organization_id: uuid.UUID` as a bare,
unauthenticated FastAPI query parameter on every list endpoint (e.g.
`list_printers(organization_id: uuid.UUID, ...)`), so any caller could read
any organization's profiles by guessing or enumerating UUIDs — there was no
session, no token, no membership check at all. In the rebuild,
`organization_id` only ever appears as a path segment that is *verified*
against the caller's own memberships, never as a value the server trusts on
its own. `backend/tests/test_tenant_isolation.py` exercises this directly:
org A's JWT against org B's `organization_id` in the path gets 403 on list,
get, and delete.

## Plan limit enforcement

`app/services/plan_limits.enforce_plan_limit(session, organization, field,
count_stmt)` loads the org's `Plan`, and if the named limit column (e.g.
`max_shops`) is non-NULL, counts existing rows via the caller-supplied
`count_stmt` and raises `402 Payment Required` if creating one more would
meet or exceed it. Wired into `create_shop`, `create_toolbox`, and
`create_drawer`. NULL limit columns (the `pro` plan) always pass.

## Deployment topology

Six containers, one Postgres, one Redis, matching this homelab's
`cardforge-v2` conventions (chosen over older/looser sibling patterns):

| service | image/build | networks | notes |
|---|---|---|---|
| `workshopos-postgres` | `postgres:16-bookworm` | `workshopos` | named volume, `pg_isready` healthcheck |
| `workshopos-redis` | `redis:7-bookworm` | `workshopos` | named volume, `redis-cli ping` healthcheck |
| `workshopos-migrate` | backend image, `command: alembic upgrade head` | `workshopos` | `restart: "no"`, exits 0, gates api/worker |
| `workshopos-api` | backend image, `command: uvicorn app.main:app --host 0.0.0.0 --port 8000` | `workshopos`, `apps` | dependency-free `/health`, Python urllib healthcheck |
| `workshopos-worker` | backend image, `command: dramatiq app.workers.tasks` | `workshopos` | no geometry actor wired yet (M2) |
| `workshopos-frontend` | node build → `nginx:1.27-alpine` | `workshopos`, `apps`, `web` | only service publishing a host port (`${APP_PORT:-3027}`) |

`backend/Dockerfile` is one multi-stage image shared by `migrate`/`api`/
`worker` — no baked `CMD`, behavior selected entirely via compose's
`command:` per service. The builder stage installs `backend/requirements.txt`
and `pip install ./geometry` so `import workshop_geometry` works from the
runtime stage without needing the geometry source tree at runtime.

Not part of this repo (applied separately, shared infra):
`apps/caddy/sites/workshopos.caddy` reverse-proxying to
`workshopos-frontend:3027`, matching `apps/caddy/sites/cardforge-v2.caddy`.
