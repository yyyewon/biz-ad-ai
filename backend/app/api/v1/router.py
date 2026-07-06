from fastapi import APIRouter
from importlib import import_module

api_router = APIRouter()


def _include_router_if_available(
    module_path: str,
    *,
    prefix: str = "",
    tags: list[str] | None = None,
) -> None:
    try:
        module = import_module(module_path)
    except Exception:
        return
    router = getattr(module, "router", None)
    if router is not None:
        api_router.include_router(router, prefix=prefix, tags=tags)


_include_router_if_available("app.api.v1.endpoints.health", prefix="/health", tags=["Health"])
_include_router_if_available(
    "app.api.v1.endpoints.image_preprocess",
    prefix="/image",
    tags=["Image Preprocess"],
)
_include_router_if_available("app.api.v1.endpoints.auth", prefix="/auth", tags=["Auth"])
_include_router_if_available(
    "app.api.v1.endpoints.generate_ad",
    prefix="/ad/generate",
    tags=["Generate Ad"],
)
_include_router_if_available("app.api.v1.endpoints.image_ad")
