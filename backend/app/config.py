from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "WorkshopOS"
    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str
    redis_url: str = "redis://workshopos-redis:6379/0"

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 720

    generated_files_dir: str = "/data/generated"

    # --- Billing / plan enforcement -------------------------------------
    # "saas" (Stripe subscriptions) or "self_hosted" (offline license keys).
    # Gates which of the two upgrade mechanisms is active; self_hosted is
    # the correct default for a fresh self-hosted install.
    deployment_mode: str = "self_hosted"
    # Ed25519 public key (PEM), used to verify self-hosted license keys
    # offline. Only needed when deployment_mode == "self_hosted".
    license_public_key: str | None = None
    # Stripe test/live-mode secret key + webhook signing secret. Only needed
    # when deployment_mode == "saas".
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    # Base URL this deployment is publicly reachable at -- needed to build
    # Stripe Checkout success_url/cancel_url and billing portal return_url.
    app_public_url: str = "http://localhost:3027"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
