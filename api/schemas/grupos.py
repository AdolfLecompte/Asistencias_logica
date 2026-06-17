from datetime import datetime

from pydantic import BaseModel


class GrupoCreate(BaseModel):
    telegram_chat_id: str
    nombre: str
    materia: str | None = None


class GrupoUpdate(BaseModel):
    nombre: str | None = None
    materia: str | None = None
    activo: bool | None = None


class GrupoResponse(BaseModel):
    id: int
    telegram_chat_id: str
    nombre: str
    materia: str | None
    activo: bool
    creado_en: datetime


class ProfesorEnGrupo(BaseModel):
    id: int
    nombre: str
    apellido: str | None
    username: str | None
    asignado_en: datetime


class EstudianteEnGrupo(BaseModel):
    id: int
    nombre: str
    apellido: str | None
    username: str | None
    inscrito_en: datetime
    activo: bool


class AsignarProfesorRequest(BaseModel):
    profesor_id: int


class ActualizarInscripcionRequest(BaseModel):
    activo: bool
