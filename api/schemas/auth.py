from pydantic import BaseModel


class LoginRequest(BaseModel):
    login: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ProfesorMe(BaseModel):
    id: int
    telegram_user_id: int
    login: str
    username: str | None
    nombre: str
    apellido: str | None
    email: str | None
