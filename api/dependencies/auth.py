from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from api.core.database import get_conn
from api.core.security import decode_token

bearer = HTTPBearer()


async def get_current_profesor(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict:
    """Valida el JWT y retorna los datos del profesor autenticado."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise credentials_error
        profesor_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise credentials_error

    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT id, telegram_user_id, login, nombre, apellido, username, email, activo, rol, grupo_id "
            "FROM profesores WHERE id = $1",
            profesor_id,
        )

    if not row or not row["activo"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Profesor no encontrado o inactivo.",
        )

    return dict(row)


async def require_admin(profesor: dict = Depends(get_current_profesor)) -> dict:
    """Verifica que el profesor autenticado tenga rol admin."""
    if profesor.get("rol") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de administrador.",
        )
    return profesor


async def get_profesor_en_grupo(grupo_id: int, profesor: dict = Depends(get_current_profesor)) -> dict:
    """Verifica que el profesor autenticado esté asignado al grupo solicitado."""
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM grupo_profesores WHERE grupo_id = $1 AND profesor_id = $2",
            grupo_id,
            profesor["id"],
        )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este grupo.",
        )
    return profesor
