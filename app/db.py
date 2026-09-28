"""Хранилище на SQLite.

Почему SQLite: на пилоте это один файл, ничего не нужно поднимать,
и всё видно обычным просмотрщиком. Когда дойдём до продакшена,
меняется только этот модуль - остальной код о базе ничего не знает.
"""
import sqlite3
import threading
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS classes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    join_code   TEXT NOT NULL UNIQUE,
    teacher_id  INTEGER
);

CREATE TABLE IF NOT EXISTS users (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ext_id    TEXT NOT NULL UNIQUE,   -- идентификатор пользователя в MAX
    token     TEXT UNIQUE,            -- личный секрет для входа по ссылке (пилот без MAX)
    name      TEXT NOT NULL,          -- только имя, без фамилии
    role      TEXT NOT NULL,          -- 'teacher' | 'student'
    class_id  INTEGER REFERENCES classes(id)
);

CREATE TABLE IF NOT EXISTS questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id   INTEGER REFERENCES classes(id),  -- NULL = общая библиотека
    topic      TEXT NOT NULL,
    text       TEXT NOT NULL,
    answer     TEXT NOT NULL,
    options    TEXT NOT NULL,          -- варианты через '|'
    author_id  INTEGER REFERENCES users(id),
    status     TEXT NOT NULL DEFAULT 'approved',  -- pending | approved | rejected
    reject_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS raids (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id   INTEGER NOT NULL REFERENCES classes(id),
    topic      TEXT NOT NULL,
    hp_max     INTEGER NOT NULL,
    hp_left    INTEGER NOT NULL,
    deadline   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active',   -- active | won | closed
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS answers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    raid_id     INTEGER NOT NULL REFERENCES raids(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    is_correct  INTEGER NOT NULL,
    damage      INTEGER NOT NULL DEFAULT 0,
    skip_reason TEXT,                  -- почему урон не засчитан
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS teaching (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL REFERENCES users(id),
    class_id   INTEGER NOT NULL REFERENCES classes(id),
    subject    TEXT NOT NULL,
    UNIQUE(teacher_id, class_id, subject)
);

CREATE INDEX IF NOT EXISTS idx_answers_raid ON answers(raid_id);
CREATE INDEX IF NOT EXISTS idx_answers_user ON answers(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic, status);
"""

# Соединение своё на каждый поток: SQLite запрещает делить его между потоками,
# а мини-приложение обслуживает запросы в нескольких потоках сразу.
_local = threading.local()
_path: str = config.DB_PATH


def connect(path: str | None = None) -> sqlite3.Connection:
    """Задаёт файл базы и открывает соединение для текущего потока."""
    global _path
    if path:
        _path = path
    _close_local()
    return conn()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        try:
            c = sqlite3.connect(_path)
            c.execute("PRAGMA journal_mode = WAL")   # чтение не блокирует запись
        except sqlite3.OperationalError as e:
            raise RuntimeError(
                f"Не удалось открыть базу {_path}: {e}\n"
                "Так бывает на сетевых и облачных папках (iCloud, Dropbox, сетевой диск): "
                "SQLite нужны файловые блокировки, которых там нет.\n"
                "Запустите с базой в обычной папке, например:\n"
                "    DB_PATH=~/boss.db python3 run_web.py"
            ) from e
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        c.executescript(SCHEMA)
        # мягкая миграция для баз, созданных прежней версией
        for stmt in (
            "ALTER TABLE users ADD COLUMN token TEXT",
            "ALTER TABLE raids ADD COLUMN subject TEXT",
            "ALTER TABLE questions ADD COLUMN subject TEXT",
            "ALTER TABLE raids ADD COLUMN boss TEXT",
            "ALTER TABLE questions ADD COLUMN skill TEXT",
        ):
            try:
                c.execute(stmt)
            except sqlite3.OperationalError:
                pass
        # предмет по умолчанию для данных, заведённых до появления предметов
        c.execute("UPDATE raids SET subject = ? WHERE subject IS NULL OR subject = ''",
                  (config.DEFAULT_SUBJECT,))
        c.execute("UPDATE questions SET subject = ? WHERE subject IS NULL OR subject = ''",
                  (config.DEFAULT_SUBJECT,))
        # старая связь «учитель принадлежит классу» переезжает в teaching
        c.execute(
            "INSERT OR IGNORE INTO teaching (teacher_id, class_id, subject)"
            " SELECT u.id, cl.id, ? FROM classes cl JOIN users u ON u.id = cl.teacher_id"
            " WHERE u.role = 'teacher'",
            (config.DEFAULT_SUBJECT,))
        c.commit()
        _local.conn = c
    return c


def _close_local() -> None:
    c = getattr(_local, "conn", None)
    if c is not None:
        c.close()
        _local.conn = None


def close() -> None:
    _close_local()


@contextmanager
def tx():
    """Транзакция: либо всё, либо ничего."""
    c = conn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise


def q(sql: str, *args) -> list[sqlite3.Row]:
    return conn().execute(sql, args).fetchall()


def q1(sql: str, *args) -> sqlite3.Row | None:
    return conn().execute(sql, args).fetchone()


def run(sql: str, *args) -> int:
    """Выполняет запрос и возвращает id вставленной строки."""
    with tx() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid
