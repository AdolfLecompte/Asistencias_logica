from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError

from api.core.database import get_conn
from api.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from api.dependencies.auth import get_current_profesor
from api.schemas.auth import LoginRequest, ProfesorMe, RefreshRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT id, telegram_user_id, password_hash, activo FROM profesores WHERE login = $1",
            body.login,
        )

    if not row or not row["activo"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        )

    if not row["password_hash"] or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas.",
        )

    return TokenResponse(
        access_token=create_access_token(row["id"], row["telegram_user_id"]),
        refresh_token=create_refresh_token(row["id"]),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest):
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError
        profesor_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token inválido.")

    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT id, telegram_user_id, activo FROM profesores WHERE id = $1",
            profesor_id,
        )

    if not row or not row["activo"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Profesor no encontrado.")

    return TokenResponse(
        access_token=create_access_token(row["id"], row["telegram_user_id"]),
        refresh_token=create_refresh_token(row["id"]),
    )


@router.get("/me", response_model=ProfesorMe)
async def me(profesor: dict = Depends(get_current_profesor)):
    return ProfesorMe(**profesor)
