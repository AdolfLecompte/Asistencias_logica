import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.core.database import get_conn
from api.core.security import hash_password
from api.dependencies.auth import require_admin

router = APIRouter(prefix="/profesores", tags=["Profesores"])


class ProfesorListItem(BaseModel):
    id: int
    nombre: str
    apellido: str | None
    username: str | None
    email: str | None
    rol: str
    grupo_id: int | None
    grupo_nombre: str | None


class AsignarGrupoRequest(BaseModel):
    grupo_id: int | None


class CrearProfesorRequest(BaseModel):
    nombre: str
    apellido: str | None = None
    login: str
    password: str
    email: str | None = None
    rol: str = "profesor"
    grupo_id: int | None = None


@router.get("", response_model=list[ProfesorListItem])
async def listar_profesores(admin: dict = Depends(require_admin)):
    """Lista todos los profesores con su grupo asignado."""
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (p.id)
                   p.id, p.nombre, p.apellido, p.username, p.email, p.rol,
                   COALESCE(p.grupo_id, gp.grupo_id) AS grupo_id,
                   g.nombre AS grupo_nombre
            FROM profesores p
            LEFT JOIN grupo_profesores gp ON gp.profesor_id = p.id
            LEFT JOIN grupos g ON g.id = COALESCE(p.grupo_id, gp.grupo_id)
            ORDER BY p.id, p.nombre
            """
        )
    return [dict(r) for r in rows]


@router.patch("/{profesor_id}/grupo", response_model=ProfesorListItem)
async def asignar_grupo(
    profesor_id: int,
    body: AsignarGrupoRequest,
    admin: dict = Depends(require_admin),
):
    """Admin asigna o cambia el grupo de un profesor."""
    async with get_conn() as conn:
        # Verificar que el profesor existe
        existe = await conn.fetchrow(
            "SELECT id FROM profesores WHERE id = $1", profesor_id
        )
        if not existe:
            raise HTTPException(status_code=404, detail="Profesor no encontrado.")

        # Verificar que el grupo existe (si se pasa uno)
        if body.grupo_id is not None:
            grupo = await conn.fetchrow(
                "SELECT id FROM grupos WHERE id = $1", body.grupo_id
            )
            if not grupo:
                raise HTTPException(status_code=404, detail="Grupo no encontrado.")

        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE profesores SET grupo_id = $1 WHERE id = $2
                RETURNING id, nombre, apellido, username, email, rol, grupo_id
                """,
                body.grupo_id,
                profesor_id,
            )

            # Sincronizar grupo_profesores
            await conn.execute(
                "DELETE FROM grupo_profesores WHERE profesor_id = $1", profesor_id
            )
            if body.grupo_id is not None:
                await conn.execute(
                    """INSERT INTO grupo_profesores (grupo_id, profesor_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING""",
                    body.grupo_id, profesor_id,
                )

        grupo_nombre = None
        if row["grupo_id"]:
            g = await conn.fetchrow(
                "SELECT nombre FROM grupos WHERE id = $1", row["grupo_id"]
            )
            grupo_nombre = g["nombre"] if g else None

    return {**dict(row), "grupo_nombre": grupo_nombre}


@router.delete("/{profesor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_profesor(
    profesor_id: int,
    admin: dict = Depends(require_admin),
):
    """Admin elimina un profesor. No se puede eliminar al admin principal (login='admin')."""
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT id, login FROM profesores WHERE id = $1", profesor_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Profesor no encontrado.")
        if row["login"] == "admin":
            raise HTTPException(
                status_code=403,
                detail="No se puede eliminar al administrador principal.",
            )
        try:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM grupo_profesores WHERE profesor_id = $1", profesor_id
                )
                await conn.execute(
                    "DELETE FROM profesores WHERE id = $1", profesor_id
                )
        except Exception:
            raise HTTPException(
                status_code=409,
                detail="No se puede eliminar: el instructor tiene registros asociados (historial de modificaciones).",
            )


@router.post("", response_model=ProfesorListItem, status_code=status.HTTP_201_CREATED)
async def crear_profesor(
    body: CrearProfesorRequest,
    admin: dict = Depends(require_admin),
):
    """Admin crea un nuevo profesor/instructor."""
    password_hash = hash_password(body.password)
    async with get_conn() as conn:
        # Verificar login único
        existe = await conn.fetchrow(
            "SELECT id FROM profesores WHERE login = $1", body.login
        )
        if existe:
            raise HTTPException(status_code=409, detail="El login ya está en uso.")

        # Verificar grupo si se pasa
        if body.grupo_id is not None:
            grupo = await conn.fetchrow(
                "SELECT id FROM grupos WHERE id = $1", body.grupo_id
            )
            if not grupo:
                raise HTTPException(status_code=404, detail="Grupo no encontrado.")

        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO profesores
                    (telegram_user_id, login, password_hash, nombre, apellido, email, rol, grupo_id, activo)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE)
                RETURNING id, nombre, apellido, username, email, rol, grupo_id
                """,
                f"web_{uuid.uuid4()}",
                body.login,
                password_hash,
                body.nombre,
                body.apellido,
                body.email,
                body.rol,
                body.grupo_id,
            )
            if body.grupo_id is not None:
                await conn.execute(
                    """INSERT INTO grupo_profesores (grupo_id, profesor_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING""",
                    body.grupo_id, row["id"],
                )

        grupo_nombre = None
        if row["grupo_id"]:
            g = await conn.fetchrow(
                "SELECT nombre FROM grupos WHERE id = $1", row["grupo_id"]
            )
            grupo_nombre = g["nombre"] if g else None

    return {**dict(row), "grupo_nombre": grupo_nombre}
