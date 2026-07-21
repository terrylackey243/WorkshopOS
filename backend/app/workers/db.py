import asyncio

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ..config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Dedicated engine for worker actors -- deliberately NOT `app.db.engine`
# (the pooled engine FastAPI's request-scoped `get_session` uses).
#
# Each actor invocation runs its own `asyncio.run()`, which spins up a brand
# new event loop every time. asyncpg connections are permanently bound to
# the event loop that created them, but a *pooled* engine hands back
# connections opened under a previous call's now-closed loop, raising
# "RuntimeError: Task ... got Future ... attached to a different loop" the
# moment the pool tries to reuse one. This bit both `generate_design` and
# `generate_bin_design` intermittently -- it only "worked" in early testing
# by luck (first-ever checkout from an empty pool never collides).
#
# NullPool opens a fresh DBAPI connection on every checkout and closes it on
# checkin -- no connection ever outlives the event loop that created it, so
# there's nothing to go stale across `asyncio.run()` calls. The per-job
# connection-setup cost is negligible here: worker jobs are infrequent and
# already dominated by CSG boolean-op time, not connection overhead.
worker_engine = create_async_engine(settings.database_url, poolclass=NullPool)
WorkerSessionFactory = async_sessionmaker(worker_engine, expire_on_commit=False)

# --- Eager warm-up: closes a second, subtler "different loop" race NullPool
# alone doesn't cover -----------------------------------------------------
#
# NullPool (above) guarantees no DBAPI *connection* outlives the event loop
# that created it. But `worker_engine` itself is still a single object
# shared by every dramatiq worker *thread* in this process (dramatiq runs a
# thread pool per forked process, not one thread per process), and
# SQLAlchemy's dialect-initialization event ("run this setup exactly once
# across the engine's lifetime") is internally guarded by a lazily-created
# `asyncio.Lock`. That lock gets permanently bound to whichever thread's
# event loop first touches the engine. If a second thread's `asyncio.run()`
# loop reaches that same one-time-init path concurrently -- entirely
# possible here, since `process_uploaded_insert` is fast enough that a
# handful of near-simultaneous uploads routinely land multiple worker
# threads on their *first-ever* use of `worker_engine` at the same instant
# -- SQLAlchemy raises "<Lock ...> is bound to a different event loop", or
# worse, the second thread can block forever waiting on a lock tied to a
# loop that already exited, hanging until Dramatiq's `time_limit` kills the
# thread (observed in practice: a job stuck in `queued` indefinitely,
# rather than a clean failed/retried message).
#
# Because this init-once guard really does only run once per engine
# lifetime, resolving it synchronously and single-threadedly here --
# at module import, which happens once per process before dramatiq forks
# and/or spawns its worker thread pool -- makes every later concurrent
# first-use a no-op fast path instead of a race. If this warm-up itself
# fails (e.g. Postgres briefly unreachable at process boot), we log and
# move on rather than crashing the import: worst case, the original
# (rare, self-healing-via-retry) race is still possible, which is exactly
# the pre-fix behavior, not a regression.
async def _warm_up_worker_engine() -> None:
    async with worker_engine.connect():
        pass


try:
    asyncio.run(_warm_up_worker_engine())
except Exception:  # noqa: BLE001 -- best-effort; see comment above
    logger.warning("worker_engine_warm_up_failed", exc_info=True)
