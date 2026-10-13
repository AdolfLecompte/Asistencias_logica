-- =============================================================
-- SCHEMA PostgreSQL — Bot de Asistencias
-- =============================================================

-- -------------------------------------------------------------
-- TIPOS ENUMERADOS
-- -------------------------------------------------------------

CREATE TYPE estado_asistencia AS ENUM (
    'asistio',
    'ausente_justificado',     -- ausente, evidencia aceptada por IA o profesor
    'ausente_injustificado',   -- ausente, sin evidencia válida
    'pendiente_revision'       -- no respondió la encuesta, o evidencia sin analizar
);

CREATE TYPE resultado_ia AS ENUM (
    'valido',
    'invalido',
    'timeout',
    'error',
    'sin_analisis'
);

-- -------------------------------------------------------------
-- PROFESORES
-- Administradores del bot. Mapeados 1:1 con un user_id de Telegram.
-- -------------------------------------------------------------

CREATE TABLE profesores (
    id                BIGSERIAL       PRIMARY KEY,
    telegram_user_id  BIGINT          NOT NULL UNIQUE,
    login             VARCHAR(64)     NOT NULL UNIQUE,
    password_hash     TEXT            NOT NULL,
    username          VARCHAR(64),
    nombre            VARCHAR(128)    NOT NULL,
    apellido          VARCHAR(128),
    email             VARCHAR(256),
    activo            BOOLEAN         NOT NULL DEFAULT TRUE,
    creado_en         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    actualizado_en    TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------
-- ESTUDIANTES
-- Se crean automáticamente al registrar su primera asistencia.
-- -------------------------------------------------------------

CREATE TABLE estudiantes (
    id                BIGSERIAL       PRIMARY KEY,
    telegram_user_id  BIGINT          NOT NULL UNIQUE,
    username          VARCHAR(64),
    nombre            VARCHAR(128)    NOT NULL,
    apellido          VARCHAR(128),
    activo            BOOLEAN         NOT NULL DEFAULT TRUE,
    creado_en         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    actualizado_en    TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------
-- GRUPOS
-- Cada grupo/canal de Telegram donde el bot opera.
-- -------------------------------------------------------------

CREATE TABLE grupos (
    id                BIGSERIAL       PRIMARY KEY,
    telegram_chat_id  BIGINT          NOT NULL UNIQUE,
    nombre            VARCHAR(256)    NOT NULL,
    materia           VARCHAR(256),
    activo            BOOLEAN         NOT NULL DEFAULT TRUE,
    creado_en         TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------
-- GRUPO_PROFESORES
-- Qué profesores administran qué grupos (N:M).
-- -------------------------------------------------------------

CREATE TABLE grupo_profesores (
    grupo_id      BIGINT      NOT NULL REFERENCES grupos(id)     ON DELETE CASCADE,
    profesor_id   BIGINT      NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    asignado_en   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (grupo_id, profesor_id)
);

-- -------------------------------------------------------------
-- GRUPO_ESTUDIANTES
-- Alumnos inscritos en cada grupo (matrícula).
-- -------------------------------------------------------------

CREATE TABLE grupo_estudiantes (
    grupo_id       BIGINT      NOT NULL REFERENCES grupos(id)      ON DELETE CASCADE,
    estudiante_id  BIGINT      NOT NULL REFERENCES estudiantes(id) ON DELETE CASCADE,
    inscrito_en    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activo         BOOLEAN     NOT NULL DEFAULT TRUE,
    PRIMARY KEY (grupo_id, estudiante_id)
);

-- -------------------------------------------------------------
-- SESIONES
-- Una sesión = una clase/encuesta. Ciclo de vida: abierta → cerrada.
-- -------------------------------------------------------------

CREATE TABLE sesiones (
    id             BIGSERIAL       PRIMARY KEY,
    grupo_id       BIGINT          NOT NULL REFERENCES grupos(id)     ON DELETE RESTRICT,
    creada_por     BIGINT          REFERENCES profesores(id)           ON DELETE SET NULL,
    descripcion    VARCHAR(512),
    automatica     BOOLEAN         NOT NULL DEFAULT FALSE,
    activa         BOOLEAN         NOT NULL DEFAULT TRUE,
    abierta_en     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    cerrada_en     TIMESTAMPTZ,

    CONSTRAINT cerrada_despues_de_abierta
        CHECK (cerrada_en IS NULL OR cerrada_en > abierta_en)
);

-- -------------------------------------------------------------
-- ASISTENCIAS
-- Registro por alumno por sesión. Inmutable por el alumno.
-- El profesor puede actualizarlo; el rastro queda en historial_modificaciones.
-- -------------------------------------------------------------

CREATE TABLE asistencias (
    id               BIGSERIAL           PRIMARY KEY,
    sesion_id        BIGINT              NOT NULL REFERENCES sesiones(id)    ON DELETE RESTRICT,
    estudiante_id    BIGINT              NOT NULL REFERENCES estudiantes(id) ON DELETE RESTRICT,

    -- Núcleo
    asistio          BOOLEAN             NOT NULL,
    estado           estado_asistencia   NOT NULL,

    -- Timestamp original del alumno (nunca cambia)
    registrado_en    TIMESTAMPTZ         NOT NULL DEFAULT NOW(),

    -- Campos de auditoría cuando el profesor edita
    modificado_en    TIMESTAMPTZ,
    modificado_por   BIGINT              REFERENCES profesores(id) ON DELETE SET NULL,

    CONSTRAINT una_respuesta_por_sesion UNIQUE (sesion_id, estudiante_id)
);

-- -------------------------------------------------------------
-- EVIDENCIAS
-- Archivos de justificante adjuntos a una asistencia.
-- Separados para no acoplar el registro principal.
--
-- Cómo distinguir los sub-casos de pendiente_revision:
--   · sin fila en evidencias  → estudiante no respondió la encuesta
--   · con fila (resultado_ia = 'timeout'|'error') → respondió pero IA falló
-- -------------------------------------------------------------

CREATE TABLE evidencias (
    id               BIGSERIAL       PRIMARY KEY,
    asistencia_id    BIGINT          NOT NULL REFERENCES asistencias(id) ON DELETE CASCADE,
    archivo_path     VARCHAR(512)    NOT NULL,
    resultado_ia     resultado_ia    NOT NULL DEFAULT 'sin_analisis',
    respuesta_ia     TEXT,
    analizado_en     TIMESTAMPTZ,
    creado_en        TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------
-- HISTORIAL_MODIFICACIONES
-- Audit trail de cada cambio de estado hecho por un profesor.
-- asistencias siempre tiene el estado vigente;
-- aquí queda el rastro completo de quién cambió qué y por qué.
-- -------------------------------------------------------------

CREATE TABLE historial_modificaciones (
    id               BIGSERIAL           PRIMARY KEY,
    asistencia_id    BIGINT              NOT NULL REFERENCES asistencias(id) ON DELETE RESTRICT,
    profesor_id      BIGINT              NOT NULL REFERENCES profesores(id)  ON DELETE RESTRICT,
    estado_anterior  estado_asistencia   NOT NULL,
    estado_nuevo     estado_asistencia   NOT NULL,
    motivo           TEXT,
    modificado_en    TIMESTAMPTZ         NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------
-- ÍNDICES
-- -------------------------------------------------------------

CREATE INDEX idx_asistencias_sesion       ON asistencias(sesion_id);
CREATE INDEX idx_asistencias_estudiante   ON asistencias(estudiante_id);
CREATE INDEX idx_sesiones_grupo_activa    ON sesiones(grupo_id, activa);
CREATE INDEX idx_historial_asistencia     ON historial_modificaciones(asistencia_id);
CREATE INDEX idx_profesores_tg            ON profesores(telegram_user_id);
CREATE INDEX idx_profesores_login         ON profesores(login);
CREATE INDEX idx_estudiantes_tg           ON estudiantes(telegram_user_id);
CREATE INDEX idx_evidencias_asistencia    ON evidencias(asistencia_id);
