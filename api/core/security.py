from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from api.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_access_token(profesor_id: int, telegram_user_id: int) -> str:
    payload = {
        "sub": str(profesor_id),
        "telegram_user_id": telegram_user_id,
        "type": "access",
        "exp": _now() + timedelta(minutes=settings.JWT_ACCESS_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(profesor_id: int) -> str:
    payload = {
        "sub": str(profesor_id),
        "type": "refresh",
        "exp": _now() + timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decodifica y valida el token. Lanza JWTError si es inválido o expirado."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
