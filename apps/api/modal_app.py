"""Modal deployment for AeroRoute FastAPI backend."""

from __future__ import annotations

from pathlib import Path

import modal

APP_NAME = "aeroroute-api"
API_ROOT = Path(__file__).resolve().parent

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements(str(API_ROOT / "requirements.txt"))
    .add_local_dir(str(API_ROOT / "app"), remote_path="/root/app")
    .add_local_dir(str(API_ROOT / "ml"), remote_path="/root/ml")
)

app = modal.App(APP_NAME)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("aeroroute-secrets")],
    timeout=120,
)
@modal.asgi_app()
def fastapi_app():
    import sys

    sys.path.insert(0, "/root")
    from app.main import app as fastapi_application

    return fastapi_application
