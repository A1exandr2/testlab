"""Подключение SQLite и начальные записи."""

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import bcrypt

from .config import ROOT, SCHEMA, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD

DB = Path(os.environ.get('TESTLAB_DB', ROOT / 'testlab.sqlite3'))


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def connect():
    db = sqlite3.connect(DB, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def one(db, sql, args=()):
    row = db.execute(sql, args).fetchone()
    return dict(row) if row else None


def rows(db, sql, args=()):
    return [dict(row) for row in db.execute(sql, args)]


def init_db():
    from .migrations import migrate_roles, correct_admin_roles

    DB.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as db:
        db.executescript(SCHEMA.read_text(encoding='utf-8'))
        with db:
            db.execute('BEGIN IMMEDIATE')
            migrate_roles(db)
            admin = one(
                db, 'SELECT id,role FROM users WHERE email=?', (DEFAULT_ADMIN_EMAIL,)
            )
            if not admin:
                password = bcrypt.hashpw(
                    DEFAULT_ADMIN_PASSWORD.encode(), bcrypt.gensalt()
                )
                uid = db.execute(
                    '''INSERT INTO users(name,email,password,role,created_at)
                    VALUES(?,?,?,?,?)''',
                    ('Администратор', DEFAULT_ADMIN_EMAIL, password, 'admin', now()),
                ).lastrowid
                admin = {'id': uid, 'role': 'admin'}
            if admin['role'] != 'admin':
                raise ValueError(
                    'Почта стандартного администратора занята обычным пользователем'
                )
            if not one(db, "SELECT key FROM app_settings WHERE key='default_group'"):
                pid = db.execute(
                    'INSERT INTO projects(name,created_by,created_at) VALUES(?,?,?)',
                    ('Общая группа', admin['id'], now()),
                ).lastrowid
                db.execute(
                    'INSERT INTO project_members VALUES(?,?,?,?)',
                    (pid, admin['id'], 'admin', now()),
                )
                db.execute(
                    "INSERT INTO app_settings VALUES('default_group',?)", (str(pid),)
                )
            correct_admin_roles(db, admin['id'])
