"""The ``/api`` router, assembled by discovery.

Every module in ``app/api/routes/`` that exposes a module-level ``router`` (an ``APIRouter``)
is included, in module-name order. A stage adds a route file; nothing shared is edited.
"""

import importlib
import pkgutil

from fastapi import APIRouter

ROUTES_PACKAGE = "app.api.routes"
API_PREFIX = "/api"


def build_api_router(package: str = ROUTES_PACKAGE) -> APIRouter:
    api = APIRouter(prefix=API_PREFIX)
    pkg = importlib.import_module(package)
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package}.{info.name}")
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            api.include_router(router)
    return api
