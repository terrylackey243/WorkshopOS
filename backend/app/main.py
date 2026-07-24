from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers.admin import router as admin_router
from .routers.ai_import import router as ai_import_router
from .routers.auth import router as auth_router
from .routers.billing import router as billing_router
from .routers.dashboard import router as dashboard_router
from .routers.designs import router as designs_router
from .routers.drawer_layouts import router as drawer_layouts_router
from .routers.drawers import router as drawers_router
from .routers.export import router as export_router
from .routers.failed_jobs import router as failed_jobs_router
from .routers.insert_designs import router as insert_designs_router
from .routers.organizations import router as organizations_router
from .routers.profiles import router as profiles_router
from .routers.roadmap import router as roadmap_router
from .routers.shops import router as shops_router
from .routers.toolboxes import router as toolboxes_router
from .routers.tools import router as tools_router
from .schemas.billing import DeploymentConfigResponse

settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")

# Local-dev convenience only; production traffic is proxied through nginx
# same-origin (see frontend/nginx.conf), so this never matters there.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(organizations_router)
app.include_router(shops_router)
app.include_router(toolboxes_router)
app.include_router(drawers_router)
app.include_router(drawer_layouts_router)
app.include_router(tools_router)
app.include_router(profiles_router)
app.include_router(designs_router)
app.include_router(insert_designs_router)
app.include_router(roadmap_router)
app.include_router(billing_router)
app.include_router(dashboard_router)
app.include_router(export_router)
app.include_router(failed_jobs_router)
app.include_router(admin_router)
app.include_router(ai_import_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Dependency-free liveness check -- this is what the compose healthcheck hits."""
    return {"status": "ok"}


@app.get("/config", response_model=DeploymentConfigResponse)
async def config() -> DeploymentConfigResponse:
    """Unauthenticated deployment-mode discovery. The frontend needs this
    before any auth state exists, to know whether to render the license-key
    panel (self_hosted) or the Stripe upgrade buttons (saas). Deliberately
    returns only `deployment_mode`, never the full Settings object."""
    return DeploymentConfigResponse(deployment_mode=get_settings().deployment_mode)
