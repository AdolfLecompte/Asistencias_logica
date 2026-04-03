from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.core.database import get_conn
from api.dependencies.auth import get_current_profesor, get_profesor_en_grupo
from api.schemas.sesiones import SesionCreate, SesionResponse

router = APIRouter(tags=["Sesiones"])


@router.get("/grupos/{grupo_id}/sesiones", response_model=list[SesionResponse])
async def listar_sesiones(
    grupo_id: int,
    activa: bool | None = Query(default=None),
    profesor: dict = Depends(get_profesor_en_grupo),
):
    filtro = "WHERE s.grupo_id = $1"
    params: list = [grupo_id]

    if activa is not None:
        params.append(activa)
        filtro += f" AND s.activa = ${len(params)}"

    async with get_conn() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                s.id, s.grupo_id, s.descripcion, s.automatica, s.activa,
                s.abierta_en, s.cerrada_en, s.creada_por,
                COUNT(*) FILTER (WHERE a.estado = 'asistio')              AS total_asistencias,
                COUNT(*) FILTER (WHERE a.estado LIKE 'ausente_%')         AS total_ausentes,
                COUNT(*) FILTER (WHERE a.estado = 'pendiente_revision')   AS total_pendientes
            FROM sesiones s
            LEFT JOIN asistencias a ON a.sesion_id = s.id
            {filtro}
            GROUP BY s.id
            ORDER BY s.abierta_en DESC
            """,
            *params,
        )
    return [dict(r) for r in rows]


@router.post(
    "/grupos/{grupo_id}/sesiones",
    response_model=SesionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def crear_sesion(
    grupo_id: int,
    body: SesionCreate,
    profesor: dict = Depends(get_profesor_en_grupo),
):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO sesiones (grupo_id, creada_por, descripcion)
            VALUES ($1, $2, $3)
            RETURNING id, grupo_id, descripcion, automatica, activa, abierta_en, cerrada_en, creada_por
            """,
            grupo_id,
            profesor["id"],
            body.descripcion,
        )
    return {**dict(row), "total_asistencias": 0, "total_ausentes": 0, "total_pendientes": 0}


@router.get("/sesiones/{sesion_id}", response_model=SesionResponse)
async def obtener_sesion(sesion_id: int, profesor: dict = Depends(get_current_profesor)):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                s.id, s.grupo_id, s.descripcion, s.automatica, s.activa,
                s.abierta_en, s.cerrada_en, s.creada_por,
                COUNT(*) FILTER (WHERE a.estado = 'asistio')              AS total_asistencias,
                COUNT(*) FILTER (WHERE a.estado LIKE 'ausente_%')         AS total_ausentes,
                COUNT(*) FILTER (WHERE a.estado = 'pendiente_revision')   AS total_pendientes
            FROM sesiones s
            LEFT JOIN asistencias a ON a.sesion_id = s.id
            WHERE s.id = $1
            GROUP BY s.id
            """,
            sesion_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Sesión no encontrada.")
    return dict(row)


@router.patch("/sesiones/{sesion_id}/cerrar", response_model=SesionResponse)
async def cerrar_sesion(sesion_id: int, profesor: dict = Depends(get_current_profesor)):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            UPDATE sesiones
            SET activa = FALSE, cerrada_en = NOW()
            WHERE id = $1 AND activa = TRUE
            RETURNING id, grupo_id, descripcion, automatica, activa, abierta_en, cerrada_en, creada_por
            """,
            sesion_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Sesión no encontrada o ya cerrada.")
    return {**dict(row), "total_asistencias": 0, "total_ausentes": 0, "total_pendientes": 0}
