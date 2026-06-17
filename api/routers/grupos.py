from fastapi import APIRouter, Depends, HTTPException, status

from api.core.database import get_conn
from api.dependencies.auth import get_current_profesor, get_profesor_en_grupo, require_admin
from api.schemas.grupos import (
    ActualizarInscripcionRequest,
    AsignarProfesorRequest,
    EstudianteEnGrupo,
    GrupoCreate,
    GrupoResponse,
    GrupoUpdate,
    ProfesorEnGrupo,
)

router = APIRouter(prefix="/grupos", tags=["Grupos"])


@router.get("/all", response_model=list[GrupoResponse])
async def listar_todos_grupos(admin: dict = Depends(require_admin)):
    """Admin: lista todos los grupos existentes."""
    async with get_conn() as conn:
        rows = await conn.fetch(
            "SELECT id, telegram_chat_id, nombre, materia, activo, creado_en FROM grupos ORDER BY nombre"
        )
    return [dict(r) for r in rows]


@router.get("", response_model=list[GrupoResponse])
async def listar_mis_grupos(profesor: dict = Depends(get_current_profesor)):
    """Grupos donde el profesor autenticado está asignado."""
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT g.id, g.telegram_chat_id, g.nombre, g.materia, g.activo, g.creado_en
            FROM grupos g
            WHERE g.id IN (
                SELECT gp.grupo_id FROM grupo_profesores gp WHERE gp.profesor_id = $1
                UNION
                SELECT p.grupo_id FROM profesores p WHERE p.id = $1 AND p.grupo_id IS NOT NULL
            )
            ORDER BY g.nombre
            """,
            profesor["id"],
        )
    return [dict(r) for r in rows]


@router.post("", response_model=GrupoResponse, status_code=status.HTTP_201_CREATED)
async def crear_grupo(body: GrupoCreate, profesor: dict = Depends(get_current_profesor)):
    async with get_conn() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "INSERT INTO grupos (telegram_chat_id, nombre, materia) VALUES ($1, $2, $3) RETURNING *",
                body.telegram_chat_id,
                body.nombre,
                body.materia,
            )
            # Asignar automáticamente al creador
            await conn.execute(
                "INSERT INTO grupo_profesores (grupo_id, profesor_id) VALUES ($1, $2)",
                row["id"],
                profesor["id"],
            )
            # Sync grupo_id en profesores si aún no tiene uno asignado
            await conn.execute(
                "UPDATE profesores SET grupo_id = $1 WHERE id = $2 AND grupo_id IS NULL",
                row["id"],
                profesor["id"],
            )
    return dict(row)


@router.get("/{grupo_id}", response_model=GrupoResponse)
async def obtener_grupo(grupo_id: int, profesor: dict = Depends(get_profesor_en_grupo)):
    async with get_conn() as conn:
        row = await conn.fetchrow("SELECT * FROM grupos WHERE id = $1", grupo_id)
    if not row:
        raise HTTPException(status_code=404, detail="Grupo no encontrado.")
    return dict(row)


@router.patch("/{grupo_id}", response_model=GrupoResponse)
async def actualizar_grupo(
    grupo_id: int,
    body: GrupoUpdate,
    profesor: dict = Depends(get_profesor_en_grupo),
):
    campos = {k: v for k, v in body.model_dump().items() if v is not None}
    if not campos:
        raise HTTPException(status_code=400, detail="No hay campos para actualizar.")

    set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(campos))
    valores = list(campos.values())

    async with get_conn() as conn:
        row = await conn.fetchrow(
            f"UPDATE grupos SET {set_clause} WHERE id = $1 RETURNING *",
            grupo_id,
            *valores,
        )
    return dict(row)


@router.delete("/{grupo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def desactivar_grupo(grupo_id: int, profesor: dict = Depends(get_profesor_en_grupo)):
    async with get_conn() as conn:
        await conn.execute("UPDATE grupos SET activo = FALSE WHERE id = $1", grupo_id)


# ── Profesores del grupo ──────────────────────────────────────

@router.get("/{grupo_id}/profesores", response_model=list[ProfesorEnGrupo])
async def listar_profesores_grupo(grupo_id: int, profesor: dict = Depends(get_profesor_en_grupo)):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, p.nombre, p.apellido, p.username, gp.asignado_en
            FROM profesores p
            JOIN grupo_profesores gp ON gp.profesor_id = p.id
            WHERE gp.grupo_id = $1
            ORDER BY p.nombre
            """,
            grupo_id,
        )
    return [dict(r) for r in rows]


@router.post("/{grupo_id}/profesores", status_code=status.HTTP_201_CREATED)
async def asignar_profesor(
    grupo_id: int,
    body: AsignarProfesorRequest,
    profesor: dict = Depends(get_profesor_en_grupo),
):
    async with get_conn() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO grupo_profesores (grupo_id, profesor_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                grupo_id,
                body.profesor_id,
            )
            # Sync grupo_id en profesores si aún no tiene uno asignado
            await conn.execute(
                "UPDATE profesores SET grupo_id = $1 WHERE id = $2 AND grupo_id IS NULL",
                grupo_id,
                body.profesor_id,
            )
    return {"detail": "Profesor asignado."}


@router.delete("/{grupo_id}/profesores/{profesor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def desasignar_profesor(
    grupo_id: int,
    profesor_id: int,
    profesor: dict = Depends(get_profesor_en_grupo),
):
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM grupo_profesores WHERE grupo_id = $1 AND profesor_id = $2",
            grupo_id,
            profesor_id,
        )


# ── Estudiantes del grupo ─────────────────────────────────────

@router.get("/{grupo_id}/estudiantes", response_model=list[EstudianteEnGrupo])
async def listar_estudiantes_grupo(grupo_id: int, profesor: dict = Depends(get_profesor_en_grupo)):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT e.id, e.nombre, e.apellido, e.username, ge.inscrito_en, ge.activo
            FROM estudiantes e
            JOIN grupo_estudiantes ge ON ge.estudiante_id = e.id
            WHERE ge.grupo_id = $1
            ORDER BY e.nombre
            """,
            grupo_id,
        )
    return [dict(r) for r in rows]


@router.patch("/{grupo_id}/estudiantes/{estudiante_id}", status_code=status.HTTP_204_NO_CONTENT)
async def actualizar_inscripcion(
    grupo_id: int,
    estudiante_id: int,
    body: ActualizarInscripcionRequest,
    profesor: dict = Depends(get_profesor_en_grupo),
):
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE grupo_estudiantes SET activo = $1 WHERE grupo_id = $2 AND estudiante_id = $3",
            body.activo,
            grupo_id,
            estudiante_id,
        )
