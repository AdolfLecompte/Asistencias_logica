# Bot de Asistencias

Sistema completo para registro de asistencias escolares mediante Telegram. Compuesto por dos servicios independientes: un **bot de Telegram** y una **API REST** para el dashboard del instructor.

---

## Arquitectura

```
┌───────────────────────── ┐        ┌──────────────────────────┐
│   BOT TELEGRAM           │        │   API REST (FastAPI)     │
│   python-telegram-bot    │        │    uvicorn + asyncpg     │
│   Proceso: python main.py│        │   Proceso: uvicorn ...   │
└────────────┬─────────────┘        └────────────┬─────────────┘
             │                                   │
             └─────────────┬─────────────────────┘
                           │
                  ┌────────▼────────┐
                  │  PostgreSQL 15+  │
                  │  asistencias_db  │
                  └─────────────────┘
```

El bot registra asistencias y valida evidencias con IA (Ollama).  
La API expone los datos al dashboard Flutter del instructor, quien puede consultar reportes y corregir estados.

---

## Requisitos

- Python 3.11+
- PostgreSQL 15+
- [Ollama](https://ollama.com) con un modelo multimodal (ej. `llava`)
- Un bot de Telegram creado en [@BotFather](https://t.me/BotFather)

---

## Estructura del proyecto

```
BOT-TELEGRAM-MEJORADO/
│
├── bot.py            # Handlers del bot Telegram
├── config.py         # Variables de entorno del bot
├── main.py           # Entry point del bot
│
├── api/
│   ├── main.py       # App FastAPI + lifespan
│   ├── core/
│   │   ├── config.py     # Settings con pydantic-settings
│   │   ├── database.py   # Pool asyncpg
│   │   └── security.py   # JWT + bcrypt
│   ├── dependencies/
│   │   └── auth.py       # Dependencias de autenticación
│   ├── routers/
│   │   ├── auth.py        # POST /login /refresh GET /me
│   │   ├── grupos.py      # CRUD grupos
│   │   ├── sesiones.py    # Gestión de sesiones
│   │   ├── asistencias.py # Ver y modificar asistencias
│   │   ├── estudiantes.py # Listado y detalle de alumnos
│   │   └── reportes.py    # Reportes por sesión/grupo/estudiante
│   └── schemas/           # Modelos Pydantic (request/response)
│
├── schema.sql        # Schema completo de PostgreSQL
├── requirements.txt
├── .env              # Variables de entorno (NO subir a git)
└── .env.example      # Plantilla de configuración
```

---

## Instalación

### 1. Clonar e instalar dependencias

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` con tus valores. Los campos obligatorios son:

| Variable | Descripción |
|---|---|
| `TELEGRAM_TOKEN` | Token del bot (BotFather) |
| `DATABASE_URL` | Cadena de conexión PostgreSQL |
| `JWT_SECRET` | Clave secreta para firmar tokens JWT |

### 3. Crear la base de datos

Conéctate como superusuario de PostgreSQL:

```bash
psql -U postgres
```

Ejecuta dentro de `psql`:

```sql
CREATE USER bot_asistencias WITH PASSWORD 'tu_password';
CREATE DATABASE asistencias_db
    WITH OWNER = bot_asistencias
    ENCODING = 'UTF8'
    TEMPLATE = template0;
\c asistencias_db
GRANT ALL ON SCHEMA public TO bot_asistencias;
\q
```

### 4. Aplicar el schema

```bash
psql -U bot_asistencias -d asistencias_db -f schema.sql
```

Esto crea todas las tablas, índices y el **usuario de prueba** (ver más abajo).

---

## Ejecución

### Bot de Telegram

```bash
source venv/bin/activate
python main.py
```

### API REST

```bash
source venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

Para producción (sin `--reload`):

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2
```

---

## Comandos del bot

| Comando | Quién puede usarlo | Descripción |
|---|---|---|
| `/start` | Todos | Muestra la ayuda |
| `/asistencia [desc]` | Admin | Abre una nueva encuesta de asistencia |
| `/reporte` | Admin | Muestra el reporte de la sesión activa |
| `/cerrar` | Admin | Cierra la sesión activa |
| `/cancelar` | Todos | Cancela un envío de justificante en curso |

Los administradores se definen en `ADMIN_IDS` en el `.env`.

---

## API REST

Base URL: `http://localhost:8000/api/v1`  
Documentación interactiva: `http://localhost:8000/docs`

### Autenticación

```http
POST /api/v1/auth/login
Content-Type: application/json

{ "login": "admin", "password": "admin123" }
```

Respuesta:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

Todos los demás endpoints requieren el header:
```
Authorization: Bearer <access_token>
```

### Endpoints disponibles

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/auth/login` | Login con usuario y contraseña |
| `POST` | `/auth/refresh` | Renovar access token |
| `GET` | `/auth/me` | Datos del profesor autenticado |
| `GET` | `/grupos` | Grupos del profesor |
| `POST` | `/grupos` | Crear grupo |
| `GET` | `/grupos/{id}` | Detalle del grupo |
| `PATCH` | `/grupos/{id}` | Actualizar grupo |
| `GET` | `/grupos/{id}/profesores` | Profesores del grupo |
| `POST` | `/grupos/{id}/profesores` | Asignar profesor al grupo |
| `GET` | `/grupos/{id}/estudiantes` | Estudiantes inscritos |
| `GET` | `/grupos/{id}/sesiones` | Sesiones del grupo |
| `POST` | `/grupos/{id}/sesiones` | Crear sesión |
| `GET` | `/sesiones/{id}` | Detalle de sesión |
| `PATCH` | `/sesiones/{id}/cerrar` | Cerrar sesión |
| `GET` | `/sesiones/{id}/asistencias` | Asistencias de la sesión |
| `GET` | `/asistencias/{id}` | Detalle + historial de una asistencia |
| `PATCH` | `/asistencias/{id}/estado` | **Modificar estado** (genera historial) |
| `GET` | `/evidencias/{asistencia_id}/archivo` | Descargar imagen de justificante |
| `GET` | `/estudiantes` | Listado global de estudiantes |
| `GET` | `/estudiantes/{id}` | Perfil del estudiante |
| `GET` | `/estudiantes/{id}/asistencias` | Historial de asistencias del alumno |
| `GET` | `/reportes/sesion/{id}` | Reporte completo de una sesión |
| `GET` | `/reportes/grupo/{id}` | Serie temporal de asistencia del grupo |
| `GET` | `/reportes/estudiante/{id}?grupo_id=X` | Estadísticas de un alumno en un grupo |

---

## Base de datos

### Tablas principales

| Tabla | Descripción |
|---|---|
| `profesores` | Instructores/admins del sistema |
| `estudiantes` | Alumnos (se crean automáticamente al responder) |
| `grupos` | Grupos o cursos de Telegram |
| `grupo_profesores` | Qué profesores administran qué grupos |
| `grupo_estudiantes` | Alumnos inscritos por grupo |
| `sesiones` | Cada encuesta de asistencia |
| `asistencias` | Registro inmutable por alumno por sesión |
| `evidencias` | Fotos de justificante con resultado de IA |
| `historial_modificaciones` | Audit trail de cambios hechos por profesores |

### Estados de asistencia

| Estado | Significado |
|---|---|
| `asistio` | El alumno confirmó asistencia |
| `ausente_justificado` | Ausente con justificante válido |
| `ausente_injustificado` | Ausente sin justificante válido |
| `pendiente_revision` | No respondió la encuesta, o evidencia sin analizar |

> Las asistencias son **inmutables por el alumno**. Solo el instructor puede cambiar el estado desde el dashboard; cada cambio queda registrado en `historial_modificaciones`.

---

## Usuario de prueba

> ⚠️ Solo para desarrollo. **Eliminar en producción.**

| Campo | Valor |
|---|---|
| Login | `admin` |
| Password | `admin123` |
| Nombre | Admin Test |
| Email | admin@test.local |

Para eliminarlo en producción:
```sql
DELETE FROM profesores WHERE login = 'admin';
```

Para crear un profesor real:
```sql
INSERT INTO profesores (telegram_user_id, login, password_hash, nombre, apellido, email)
VALUES (
    123456789,  -- tu Telegram user_id (@userinfobot)
    'mi_login',
    -- genera el hash con: python -c "import bcrypt; print(bcrypt.hashpw(b'mi_password', bcrypt.gensalt()).decode())"
    '$2b$12$...',
    'Mi Nombre',
    'Mi Apellido',
    'mi@email.com'
);
```

---

## Variables de entorno — referencia completa

```env
# ── Bot Telegram ─────────────────────────────────
TELEGRAM_TOKEN=          # Token de BotFather (obligatorio)
GRUPO_ID=0               # ID del grupo para encuestas automáticas (0 = desactivado)
ADMIN_IDS=               # Telegram user_ids separados por coma
NOMBRE_MATERIA=Clase

# ── Ollama (validación de evidencias con IA) ─────
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llava        # Debe ser un modelo multimodal (soporta imágenes)

# ── Almacenamiento ───────────────────────────────
DB_FILE=asistencias.db   # SQLite del bot (uso interno del bot)
EVIDENCIAS_DIR=evidencias

# ── Horario automático ───────────────────────────
DIAS_CLASE=0,2,4         # 0=Lun … 6=Dom
HORA_INICIO=08:00
TZ=America/Bogota
DURACION_ENCUESTA_MINUTOS=30

# ── API / Dashboard ──────────────────────────────
DATABASE_URL=postgresql://bot_asistencias:password@localhost:5432/asistencias_db
JWT_SECRET=              # String largo y aleatorio (obligatorio)
JWT_ACCESS_EXPIRE_MINUTES=60
JWT_REFRESH_EXPIRE_DAYS=7
CORS_ORIGINS=["http://localhost:3000"]
```

---

## Configuración para el desarrollador del frontend

Si solo vas a trabajar con la API (ej. desarrollar el dashboard Flutter) **no necesitas el token de Telegram ni Ollama**. Sigue estos pasos:

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/bot-asistencias.git
cd bot-asistencias
```

### 2. Crear entorno virtual e instalar dependencias

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Crear la base de datos

```bash
psql -U postgres -c "CREATE USER bot_asistencias WITH PASSWORD 'bot123';"
psql -U postgres -c "CREATE DATABASE asistencias_db WITH OWNER = bot_asistencias ENCODING = 'UTF8' TEMPLATE = template0;"
psql -U postgres -d asistencias_db -c "GRANT ALL ON SCHEMA public TO bot_asistencias;"
```

### 4. Aplicar el schema

Esto crea todas las tablas y el usuario de prueba `admin / admin123`:

```bash
psql -U bot_asistencias -d asistencias_db -f schema.sql
```

### 5. Configurar el .env

```bash
cp .env.example .env
```

Para trabajar solo con la API solo necesitas editar estas dos líneas en el `.env`:

```env
DATABASE_URL=postgresql://bot_asistencias:bot123@localhost:5432/asistencias_db
JWT_SECRET=cualquier_string_largo_aqui
```

El resto de variables (`TELEGRAM_TOKEN`, `OLLAMA_URL`, etc.) pueden dejarse con los valores de ejemplo.

### 6. Levantar la API

```bash
uvicorn api.main:app --reload --port 8000
```

### 7. Probar el login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"login": "admin", "password": "admin123"}'
```

O directamente desde el navegador en **http://localhost:8000/docs** (Swagger UI interactivo).

---

## Notas de desarrollo

- El **bot** usa SQLite (`aiosqlite`) como almacenamiento propio. El objetivo es migrarlo a PostgreSQL en una fase posterior para que bot y API compartan la misma base de datos.
- El modelo de Ollama debe soportar imágenes. `gemma3:4b` **no es multimodal**; usa `llava`, `llava-llama3` o `moondream` según tu hardware.
- Para obtener tu `telegram_user_id` envía un mensaje a [@userinfobot](https://t.me/userinfobot).
