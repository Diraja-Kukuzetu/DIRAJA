# tenants.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from flask import abort

# ---------------------------------------------------------
# Tenant -> Database URI map
# ---------------------------------------------------------
# Ideally pull these from env vars rather than hardcoding
# credentials here, e.g. os.getenv("DIRAJA_DB_URI")
# ---------------------------------------------------------
TENANT_DATABASES = {
    "diraja": os.getenv(
        "DIRAJA_DB_URI",
        "mysql+pymysql://admin:MyNewPass@localhost/Diraja"
    ),
    "shwariliving": os.getenv(
        "SHWARILIVING_DB_URI",
        "mysql+pymysql://admin:MyNewPass@localhost/ShwariLiving"
    ),
    # Add new tenants here as you onboard them:
    # "newtenant": os.getenv("NEWTENANT_DB_URI", "mysql+pymysql://..."),
}

# ---------------------------------------------------------
# Engine cache — one persistent Engine per tenant,
# reused across requests instead of reconnecting each time
# ---------------------------------------------------------
_engines = {}


def get_engine_for_tenant(tenant: str):
    """
    Return a cached SQLAlchemy Engine for the given tenant slug.
    Aborts with 404 if the tenant is unknown.
    """
    if not tenant or tenant not in TENANT_DATABASES:
        abort(404, description=f"Unknown tenant '{tenant}'")

    if tenant not in _engines:
        _engines[tenant] = create_engine(
            TENANT_DATABASES[tenant],
            pool_pre_ping=True,   # avoids stale/dropped connections
            pool_recycle=280,     # recycle before MySQL's wait_timeout kills it
            pool_size=5,
            max_overflow=10,
        )

    return _engines[tenant]


def get_all_tenants():
    """Utility — useful for scripts that need to loop over every tenant DB
    (e.g. running migrations, batch jobs, cron tasks)."""
    return list(TENANT_DATABASES.keys())


def dispose_all_engines():
    """Optional cleanup — call on app shutdown if you want to close
    all pooled connections cleanly."""
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()