from datetime import datetime

from pydantic import BaseModel


class EstudianteResponse(BaseModel):
    id: int
    telegram_user_id: int
    username: str | None
    nombre: str
    apellido: str | None
    activo: bool
    creado_en: datetime


class AsistenciaHistorialItem(BaseModel):
    sesion_id: int
    sesion_descripcion: str | None
    grupo_nombre: str
    materia: str | None
    estado: str
    asistio: bool
    registrado_en: datetime
