"""
Configuración central del bot de asistencias.
Todas las variables se cargan desde .env
"""
import os
import sys
from datetime import time
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _getenv(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _parse_dias_clase(val: str) -> tuple[int, ...]:
    """Convierte '0,2,4' en (0, 2, 4). Días: 0=Lunes … 6=Domingo."""
    if not val:
        return (0, 2, 4)
    try:
        dias = tuple(int(x.strip()) for x in val.split(",") if x.strip())
        # Validar rango 0–6
        if any(d < 0 or d > 6 for d in dias):
            raise ValueError("Día fuera de rango")
        return dias
    except ValueError:
        print("⚠️  DIAS_CLASE inválido, usando defecto: 0,2,4")
        return (0, 2, 4)


def _parse_hora(val: str) -> time:
    """Convierte 'HH:MM' en un objeto time. Acepta también 'HH:MM:SS'."""
    if not val:
        return time(8, 0)
    try:
        parts = val.strip().split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        s = int(parts[2]) if len(parts) > 2 else 0
        return time(h, m, s)
    except (ValueError, IndexError):
        print("⚠️  HORA_INICIO inválida, usando defecto: 08:00")
        return time(8, 0)


def _parse_admin_ids(val: str) -> frozenset[int]:
    """Convierte '123456,789012' en un frozenset de enteros."""
    if not val:
        return frozenset()
    try:
        return frozenset(int(x.strip()) for x in val.split(",") if x.strip())
    except ValueError:
        print("⚠️  ADMIN_IDS inválido, se ignora la restricción de admins.")
        return frozenset()


# ── Zona horaria ────────────────────────────────────────────────────────────
ZONA_HORARIA = ZoneInfo(_getenv("TZ", "America/Bogota"))

# ── Token (obligatorio) ─────────────────────────────────────────────────────
TELEGRAM_TOKEN = _getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "TU_TOKEN_AQUI":
    print("❌ ERROR: Define TELEGRAM_TOKEN en .env")
    sys.exit(1)

# ── Grupo / Chat ─────────────────────────────────────────────────────────────
try:
    GRUPO_ID = int(_getenv("GRUPO_ID", "0") or "0")
except ValueError:
    print("⚠️  GRUPO_ID inválido, encuestas automáticas desactivadas.")
    GRUPO_ID = 0

# ── Administradores ──────────────────────────────────────────────────────────
# Lista de user_id separados por coma. Si está vacío, cualquiera puede usar los comandos.
ADMIN_IDS: frozenset[int] = _parse_admin_ids(_getenv("ADMIN_IDS", ""))

# ── Configuración del bot ────────────────────────────────────────────────────
NOMBRE_MATERIA = _getenv("NOMBRE_MATERIA", "Clase")
OLLAMA_URL     = _getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL   = _getenv("OLLAMA_MODEL", "gemma3:4b")
DATABASE_URL   = _getenv("DATABASE_URL", "postgresql://bot_asistencias:bot123@localhost:5432/asistencias_db")
EVIDENCIAS_DIR = _getenv("EVIDENCIAS_DIR", "evidencias")

# ── Horario automático ───────────────────────────────────────────────────────
DIAS_CLASE  = _parse_dias_clase(_getenv("DIAS_CLASE", "0,1,3"))  # PTB v20+: 0=Dom,1=Lun,...,6=Sáb
HORA_INICIO = _parse_hora(_getenv("HORA_INICIO", "8:00")).replace(tzinfo=ZONA_HORARIA)
DURACION_ENCUESTA_MINUTOS = int(_getenv("DURACION_ENCUESTA_MINUTOS", "30") or "30")
