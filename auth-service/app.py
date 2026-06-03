import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.service_config import service_settings
from shared.notification_client import register_error_logging
from shared.eureka_lookup import get_service_url as lookup_service_url
from shared.service_runner import prepare_service_port
from shared.jwt_auth import SECRET_KEY
from shared.circuit_breaker import resilient_request, CircuitOpenError

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from jose import jwt
from datetime import datetime, timedelta

import requests
import uvicorn
import py_eureka_client.eureka_client as eureka

SETTINGS = service_settings(default_port=8001, app_name="AUTH-SERVICE")

prepare_service_port(SETTINGS)

app = FastAPI(title="Auth Service")

register_error_logging(app, "AUTH-SERVICE", SETTINGS["eureka_server"])
ALGORITHM = "HS256"


class LoginRequest(BaseModel):
    username: str
    password: str


async def get_employee_service_url():
    return await lookup_service_url(
        SETTINGS["eureka_server"],
        "EMPLOYEE-SERVICE",
    )


@app.on_event("startup")
async def startup():
    await eureka.init_async(
        eureka_server=SETTINGS["eureka_server"],
        app_name=SETTINGS["app_name"],
        instance_host=SETTINGS["instance_host"],
        instance_port=SETTINGS["instance_port"],
    )
    print(
        f"{SETTINGS['app_name']} registered with Eureka "
        f"at {SETTINGS['instance_host']}:{SETTINGS['instance_port']}"
    )


@app.get("/health")
def health():
    return {"status": "UP"}


@app.post("/login")
async def login(request: LoginRequest):
    employee_service_url = await get_employee_service_url()

    try:
        response = resilient_request(
            "EMPLOYEE-SERVICE",
            "get",
            f"{employee_service_url}/employee/username/{request.username}",
            timeout=5,
        )
    except CircuitOpenError:
        raise HTTPException(
            status_code=503,
            detail="Employee service temporarily unavailable",
        )
    except requests.RequestException:
        raise HTTPException(
            status_code=503,
            detail="Failed to contact employee service",
        )

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid username")

    employee = response.json()

    if employee["password"] != request.password:
        raise HTTPException(status_code=401, detail="Invalid password")

    payload = {
        "sub": str(employee["id"]),
        "employee_id": employee["id"],
        "username": employee["username"],
        "name": employee["name"],
        "role": employee["role"],
        "exp": datetime.utcnow() + timedelta(hours=1),
    }

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    return {
        "access_token": token,
        "token_type": "Bearer",
        "employee": {
            "id": employee["id"],
            "username": employee["username"],
            "name": employee["name"],
            "role": employee["role"],
        },
    }


if __name__ == "__main__":
    prepare_service_port(SETTINGS)
    uvicorn.run(app, host="0.0.0.0", port=SETTINGS["port"])
