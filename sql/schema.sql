PRAGMA journal_mode=WAL;

-- Пользователи приложения.
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL UNIQUE,
    password   BLOB NOT NULL,
    role       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Сессии входа пользователей.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    csrf       TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);

-- Группы для совместной работы.
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by  INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL
);

-- Участники групп.
CREATE TABLE IF NOT EXISTS project_members (
    project_id INTEGER NOT NULL REFERENCES projects(id),
    user_id    INTEGER NOT NULL REFERENCES users(id),
    role       TEXT NOT NULL,
    joined_at  TEXT NOT NULL,
    PRIMARY KEY (project_id, user_id)
);

-- Проверки с шагами и ожидаемым результатом.
CREATE TABLE IF NOT EXISTS cases (
    id             INTEGER PRIMARY KEY,
    project_id     INTEGER NOT NULL REFERENCES projects(id),
    plan_id        INTEGER,
    requirement_id INTEGER,
    title          TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'functional',
    preconditions  TEXT NOT NULL DEFAULT '',
    steps          TEXT NOT NULL,
    expected       TEXT NOT NULL,
    created_by     INTEGER NOT NULL REFERENCES users(id),
    created_at     TEXT NOT NULL
);

-- Сохранённые результаты проверок.
CREATE TABLE IF NOT EXISTS runs (
    id               INTEGER PRIMARY KEY,
    case_id          INTEGER NOT NULL REFERENCES cases(id),
    status           TEXT NOT NULL,
    actual           TEXT NOT NULL DEFAULT '',
    environment      TEXT NOT NULL DEFAULT '',
    duration_minutes INTEGER NOT NULL DEFAULT 0,
    executed_by      INTEGER NOT NULL REFERENCES users(id),
    executed_at      TEXT NOT NULL
);

-- Служебные настройки и отметки обновлений.
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cases_project ON cases(project_id);
CREATE INDEX IF NOT EXISTS idx_runs_latest ON runs(case_id, id DESC);
