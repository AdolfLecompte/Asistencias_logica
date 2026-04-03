from fastapi import APIRouter, Depends, HTTPException, Query

from api.core.database import get_conn
from api.dependencies.auth import get_current_profesor
from api.schemas.estudiantes import AsistenciaHistorialItem, EstudianteResponse

router = APIRouter(prefix="/estudiantes", tags=["Estudiantes"])


@router.get("", response_model=list[EstudianteResponse])
async def listar_estudiantes(
    grupo_id: int | None = Query(default=None),
    profesor: dict = Depends(get_current_profesor),
):
    if grupo_id:
        async with get_conn() as conn:
            rows = await conn.fetch(
                """
                SELECT e.id, e.telegram_user_id, e.username, e.nombre, e.apellido, e.activo, e.creado_en
                FROM estudiantes e
                JOIN grupo_estudiantes ge ON ge.estudiante_id = e.id
                WHERE ge.grupo_id = $1
                ORDER BY e.nombre
                """,
                grupo_id,
            )
    else:
        async with get_conn() as conn:
            rows = await conn.fetch(
                "SELECT id, telegram_user_id, username, nombre, apellido, activo, creado_en "
                "FROM estudiantes ORDER BY nombre"
            )
    return [dict(r) for r in rows]


@router.get("/{estudiante_id}", response_model=EstudianteResponse)
async def obtener_estudiante(estudiante_id: int, profesor: dict = Depends(get_current_profesor)):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT id, telegram_user_id, username, nombre, apellido, activo, creado_en "
            "FROM estudiantes WHERE id = $1",
            estudiante_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado.")
    return dict(row)


@router.get("/{estudiante_id}/asistencias", response_model=list[AsistenciaHistorialItem])
async def historial_asistencias(
    estudiante_id: int,
    grupo_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    profesor: dict = Depends(get_current_profesor),
):
    filtro = "WHERE a.estudiante_id = $1"
    params: list = [estudiante_id]

    if grupo_id:
        params.append(grupo_id)
        filtro += f" AND g.id = ${len(params)}"

    params.extend([(page - 1) * size, size])
    offset_idx = len(params) - 1
    limit_idx = len(params)

    async with get_conn() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                s.id            AS sesion_id,
                s.descripcion   AS sesion_descripcion,
                g.nombre        AS grupo_nombre,
                g.materia,
                a.estado,
                a.asistio,
                a.registrado_en
            FROM asistencias a
            JOIN sesiones s ON s.id = a.sesion_id
            JOIN grupos g ON g.id = s.grupo_id
            {filtro}
            ORDER BY a.registrado_en DESC
            OFFSET ${offset_idx} LIMIT ${limit_idx}
            """,
            *params,
        )
    return [dict(r) for r in rows]
