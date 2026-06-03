from fastapi import HTTPException, Request
from jose import jwt, JWTError

SECRET_KEY = "my-super-secret-key-my-super-secret-key"
ALGORITHM = "HS256"


def decode_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if "employee_id" not in payload and "sub" in payload:
            try:
                payload["employee_id"] = int(payload["sub"])
            except (TypeError, ValueError):
                pass
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(request: Request) -> dict:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):].strip()
        payload = decode_jwt(token)
        employee_id = payload.get("employee_id")
        role = payload.get("role")
        username = payload.get("username")
        if not employee_id:
            raise HTTPException(
                status_code=401,
                detail="Token missing employee_id",
            )
        return {
            "employee_id": int(employee_id),
            "role": role,
            "username": username,
        }

    employee_id = request.headers.get("X-Employee-Id")
    role = request.headers.get("X-Role")
    username = request.headers.get("X-Username")

    if not employee_id:
        raise HTTPException(
            status_code=401,
            detail="Missing authenticated user",
        )

    return {
        "employee_id": int(employee_id),
        "role": role,
        "username": username,
    }