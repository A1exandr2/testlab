#!/usr/bin/env python3
"""ТестЛаб: группы, совместные проверки и результаты.

База данных — файл SQLite. Таблицы, столбцы и связи описаны в schema.sql.
Все окна браузера обращаются к одному серверу и читают один файл базы.
Ниже находятся подключение, начальная настройка и запросы для интерфейса.
"""
import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import bcrypt

ROOT = Path(__file__).resolve().parent
# Можно задать отдельный файл через TESTLAB_DB, например для тестов.
DB = Path(os.environ.get('TESTLAB_DB', ROOT / 'testlab.sqlite3'))
# Последовательно выполняет запросы обработчиков внутри этого процесса сервера.
LOCK = threading.RLock()
LOGIN_FAILURES = {}
SESSION_AGE = 12 * 3600
DEFAULT_ADMIN_EMAIL = 'admin@testlab.local'
DEFAULT_ADMIN_PASSWORD = 'Admin12345!'
STATUSES = ('not_run', 'passed', 'failed', 'blocked')
FIELD_NAMES = {'name': 'Имя или название', 'email': 'Электронная почта',
               'password': 'Пароль', 'title': 'Название проверки',
               'steps': 'Шаги проверки', 'expected': 'Ожидаемый результат',
               'actual': 'Комментарий'}


def now():
    """Единый формат даты для записей базы: время UTC с точностью до секунды."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def connect():
    """Открыть соединение с базой; вызывающий код должен затем закрыть его.

    Обычные записи сохраняются сразу (isolation_level=None). Для связанных
    изменений ниже явно используется BEGIN IMMEDIATE и блок with db.
    """
    db = sqlite3.connect(DB, timeout=10, isolation_level=None)
    # Доступ к столбцам по именам: row['email'], а не row[2].
    db.row_factory = sqlite3.Row
    # SQLite проверяет ссылки REFERENCES только при включённом foreign_keys.
    db.execute('PRAGMA foreign_keys=ON')
    # При занятой базе ждём до 10 секунд, прежде чем сообщить об ошибке записи.
    db.execute('PRAGMA busy_timeout=10000')
    return db


def one(db, sql, args=()):
    """Выполнить запрос и вернуть одну строку как словарь либо None.

    Значения пользователя передаются через args и знаки ? в SQL-запросе.
    """
    value = db.execute(sql, args).fetchone()
    return dict(value) if value else None


def rows(db, sql, args=()):
    """Вернуть все строки запроса как список словарей; без записей — пустой список."""
    return [dict(row) for row in db.execute(sql, args).fetchall()]


def init_db():
    """Подготовить базу при запуске: таблицы, совместимость, стартовый аккаунт.

    schema.sql создаёт недостающие таблицы. Старые записи не удаляются.
    Однократные переносы отмечаются в app_settings, чтобы не повторять их
    при каждом запуске. Пароль уже существующего администратора не сбрасывается.
    """
    DB.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect()) as db:
        db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        with db:
            db.execute('BEGIN IMMEDIATE')
            if not one(db, "SELECT value FROM app_settings WHERE key='simple_roles'"):
                # Старый создатель остаётся участником своей группы.
                # Его аккаунт не получает дополнительных прав.
                db.execute('''INSERT OR IGNORE INTO project_members
                    SELECT id,created_by,'member',created_at FROM projects''')
                if one(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='invites'"):
                    columns = {c['name'] for c in rows(db, 'PRAGMA table_info(invites)')}
                    if 'project_id' in columns:
                        db.execute('''INSERT OR IGNORE INTO project_members
                            SELECT project_id,used_by,'member',created_at FROM invites
                            WHERE project_id IS NOT NULL AND used_by IS NOT NULL''')
                db.execute("UPDATE users SET role='user' WHERE role!='admin'")
                db.execute("UPDATE project_members SET role='member' WHERE role!='admin'")
                db.execute("INSERT INTO app_settings VALUES('simple_roles','1')")
            admin = one(db, 'SELECT id,role FROM users WHERE email=?', (DEFAULT_ADMIN_EMAIL,))
            # Стартовый аккаунт создаётся только при его отсутствии.
            if not admin:
                cursor = db.execute('INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)',
                    ('Администратор', DEFAULT_ADMIN_EMAIL,
                     bcrypt.hashpw(DEFAULT_ADMIN_PASSWORD.encode(), bcrypt.gensalt()), 'admin', now()))
                admin = {'id': cursor.lastrowid, 'role': 'admin'}
            if admin['role'] != 'admin':
                raise ValueError('Почта стандартного администратора занята обычным пользователем')
            if not one(db, "SELECT value FROM app_settings WHERE key='default_group'"):
                # Создаём стартовую группу и запоминаем её номер для следующих запусков.
                cursor = db.execute('INSERT INTO projects(name,created_by,created_at) VALUES(?,?,?)',
                                    ('Общая группа', admin['id'], now()))
                db.execute('INSERT INTO project_members VALUES(?,?,?,?)',
                           (cursor.lastrowid, admin['id'], 'admin', now()))
                db.execute("INSERT INTO app_settings VALUES('default_group',?)", (str(cursor.lastrowid),))
            if not one(db, "SELECT value FROM app_settings WHERE key='account_roles_v2'"):
                # Исправление старой версии: владельцы групп ошибочно стали
                # администраторами аккаунтов. Однократно возвращаем им роль user.
                db.execute("UPDATE users SET role='user' WHERE email!=?", (DEFAULT_ADMIN_EMAIL,))
                db.execute("UPDATE project_members SET role='member' WHERE user_id IN (SELECT id FROM users WHERE role!='admin')")
                # При этом переносе добавляем стартового администратора в старые
                # группы без администратора. Для новых групп перенос не повторяется.
                db.execute('''INSERT OR IGNORE INTO project_members
                    SELECT p.id,?,'admin',? FROM projects p WHERE NOT EXISTS (
                        SELECT 1 FROM project_members m JOIN users u ON u.id=m.user_id
                        WHERE m.project_id=p.id AND u.role='admin')''', (admin['id'], now()))
                db.execute("UPDATE project_members SET role='admin' WHERE user_id=?", (admin['id'],))
                db.execute("INSERT INTO app_settings VALUES('account_roles_v2','1')")


def required(data, key, limit=200):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'Заполните поле «{FIELD_NAMES.get(key, key)}» (до {limit} символов)')
    return value.strip()


def optional(data, key, limit=5000):
    value = data.get(key, '')
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'Поле «{FIELD_NAMES.get(key, key)}»: максимум {limit} символов')
    return value.strip()


def ident(data, key):
    value = data.get(key)
    if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
        raise ValueError('Выберите группу или проверку')
    return int(value)


class App(BaseHTTPRequestHandler):
    server_version = 'TestLab/2.0'

    def send_json(self, obj, status=200, cookies=None):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        for cookie in cookies or []:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path, mime):
        raw = (ROOT / path).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def data(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 200_000:
                raise ValueError()
            value = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            raise ValueError('Не удалось прочитать запрос')
        if not isinstance(value, dict):
            raise ValueError('Не удалось прочитать запрос')
        return value

    def auth(self, db):
        """Найти действующий вход по хешу cookie и связанного с ним пользователя."""
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
        except Exception:
            return None
        if 'testlab_session' not in cookies:
            return None
        token_hash = hashlib.sha256(cookies['testlab_session'].value.encode()).hexdigest()
        return one(db, '''SELECT u.id,u.name,u.email,u.role,s.csrf FROM sessions s
            JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?''',
            (token_hash, int(time.time())))

    def guard(self, user):
        if not user:
            raise PermissionError('Войдите в аккаунт, чтобы продолжить')

    def project_role(self, db, user, pid):
        """Проверить участие в группе и вернуть тип аккаунта для отображения.

        Доступ даёт запись project_members. Все участники могут добавлять
        людей и проверки; значение project_members.role не повышает users.role.
        """
        membership = one(db, 'SELECT role FROM project_members WHERE project_id=? AND user_id=?', (pid, user['id']))
        if not membership:
            raise PermissionError('Нет доступа к этой группе')
        return 'admin' if user['role'] == 'admin' else 'member'

    def csrf(self, user):
        if not user or not secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), user['csrf']):
            raise PermissionError('Сессия изменилась. Обновите страницу и войдите снова')
        origin = self.headers.get('Origin')
        if origin and origin != f'http://{self.headers.get("Host")}':
            raise PermissionError('Недопустимый источник запроса')

    def dispatch(self, method):
        path = urlparse(self.path).path
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8'),
                 '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
        if method == 'GET' and path in files:
            return self.send_file(*files[path])
        if not path.startswith('/api/'):
            return self.send_json({'error': 'Страница не найдена'}, 404)
        try:
            with LOCK, closing(connect()) as db:
                user = self.auth(db)
                if method == 'GET':
                    return self.get_api(db, user, path)
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Не удалось прочитать запрос')
                data = self.data()
                if path not in ('/api/login', '/api/register'):
                    self.csrf(user)
                return self.post_api(db, user, path, data)
        except PermissionError as error:
            return self.send_json({'error': str(error)}, 403)
        except ValueError as error:
            return self.send_json({'error': str(error)}, 400)
        except sqlite3.IntegrityError:
            return self.send_json({'error': 'Такая запись уже существует. Проверьте введённые данные'}, 409)

    def do_GET(self):
        self.dispatch('GET')

    def do_POST(self):
        self.dispatch('POST')

    def get_api(self, db, user, path):
        self.guard(user)
        if path == '/api/me':
            return self.send_json({'user': {k: user[k] for k in ('id', 'name', 'email', 'role')}, 'csrf': user['csrf']})
        if path != '/api/state':
            return self.send_json({'error': 'Действие не найдено'}, 404)
        projects = rows(db, '''SELECT p.id,p.name FROM projects p JOIN project_members m
            ON m.project_id=p.id WHERE m.user_id=? ORDER BY p.name COLLATE NOCASE,p.id''', (user['id'],))
        query = parse_qs(urlparse(self.path).query).get('project', [''])[0]
        pid = ident({'project': query}, 'project') if query else (projects[0]['id'] if projects else None)
        role = self.project_role(db, user, pid) if pid else None
        result = {'user': {k: user[k] for k in ('id', 'name', 'email', 'role')},
                  'projects': projects, 'project_id': pid, 'project_role': role,
                  'users': [], 'checks': [], 'metrics': {'total': 0, **dict.fromkeys(STATUSES, 0)}}
        if pid:
            result['users'] = rows(db, '''SELECT u.id,u.name,u.email,
                CASE WHEN u.role='admin' THEN 'admin' ELSE 'member' END AS role,
                m.joined_at FROM users u JOIN project_members m ON m.user_id=u.id
                WHERE m.project_id=? ORDER BY u.name,u.id''', (pid,))
            # c — проверка, u — её создатель, r — последний сохранённый результат,
            # e — автор результата. Берём последний по id: время может совпасть.
            # LEFT JOIN оставляет в списке и проверки без результата;
            # COALESCE подставляет для них статус «Не проверено» и пустой комментарий.
            result['checks'] = rows(db, '''SELECT c.id,c.title,c.steps,c.expected,c.preconditions,
                c.created_at,u.name AS creator,COALESCE(r.status,'not_run') AS status,
                COALESCE(r.actual,'') AS actual,r.executed_at AS updated_at,e.name AS updated_by
                FROM cases c JOIN users u ON u.id=c.created_by
                LEFT JOIN runs r ON r.id=(SELECT id FROM runs WHERE case_id=c.id ORDER BY id DESC LIMIT 1)
                LEFT JOIN users e ON e.id=r.executed_by WHERE c.project_id=? ORDER BY c.id DESC''', (pid,))
            result['metrics']['total'] = len(result['checks'])
            for check in result['checks']:
                result['metrics'][check['status']] += 1
        return self.send_json(result)

    def post_api(self, db, user, path, data):
        if path == '/api/register':
            name = required(data, 'name', 80)
            email = required(data, 'email', 254).lower()
            password = required(data, 'password', 128)
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
                raise ValueError('Введите корректную электронную почту')
            if len(password) < 10:
                raise ValueError('Пароль должен содержать не менее 10 символов')
            if len(password.encode()) > 72:
                raise ValueError('Пароль слишком длинный. Используйте более короткий пароль')
            cursor = db.execute('INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)',
                (name, email, bcrypt.hashpw(password.encode(), bcrypt.gensalt()), 'user', now()))
            return self.login_response(db, cursor.lastrowid)
        if path == '/api/login':
            email = required(data, 'email', 254).lower()
            password = required(data, 'password', 128)
            attempts = [t for t in LOGIN_FAILURES.get(email, []) if time.time()-t < 300]
            if len(attempts) >= 5:
                return self.send_json({'error': 'Слишком много попыток. Повторите через 5 минут'}, 429)
            account = one(db, 'SELECT * FROM users WHERE email=?', (email,))
            valid = bool(account) and len(password.encode()) <= 72 and bcrypt.checkpw(password.encode(), account['password'])
            if not valid:
                LOGIN_FAILURES[email] = attempts + [time.time()]
                return self.send_json({'error': 'Неверная почта или пароль'}, 401)
            LOGIN_FAILURES.pop(email, None)
            return self.login_response(db, account['id'])
        self.guard(user)
        if path == '/api/logout':
            cookies = SimpleCookie()
            cookies.load(self.headers.get('Cookie', ''))
            if 'testlab_session' in cookies:
                db.execute('DELETE FROM sessions WHERE token_hash=?',
                           (hashlib.sha256(cookies['testlab_session'].value.encode()).hexdigest(),))
            return self.send_json({'ok': True}, cookies=['testlab_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'])
        if path == '/api/projects':
            title = required(data, 'name', 100)
            # Группа и участие создателя сохраняются вместе: либо обе записи,
            # либо ни одна. Создатель сразу видит группу, роль аккаунта не меняется.
            with db:
                db.execute('BEGIN IMMEDIATE')
                cursor = db.execute('INSERT INTO projects(name,created_by,created_at) VALUES(?,?,?)', (title, user['id'], now()))
                db.execute('INSERT INTO project_members VALUES(?,?,?,?)',
                           (cursor.lastrowid, user['id'], 'admin' if user['role'] == 'admin' else 'member', now()))
            return self.send_json({'id': cursor.lastrowid})
        if path not in ('/api/members', '/api/checks', '/api/checks/result'):
            return self.send_json({'error': 'Действие не найдено'}, 404)
        pid = ident(data, 'project_id')
        self.project_role(db, user, pid)
        if path == '/api/members':
            email = required(data, 'email', 254).lower()
            account = one(db, 'SELECT id,role FROM users WHERE email=?', (email,))
            if not account:
                raise ValueError('Пользователь ещё не зарегистрирован. Попросите его создать аккаунт')
            if one(db, 'SELECT user_id FROM project_members WHERE project_id=? AND user_id=?', (pid, account['id'])):
                raise ValueError('Пользователь уже состоит в этой группе')
            db.execute('INSERT INTO project_members VALUES(?,?,?,?)',
                       (pid, account['id'], 'admin' if account['role'] == 'admin' else 'member', now()))
            return self.send_json({'ok': True})
        if path == '/api/checks':
            title = required(data, 'title')
            steps = required(data, 'steps', 5000)
            expected = required(data, 'expected', 5000)
            cursor = db.execute('INSERT INTO cases(project_id,title,steps,expected,created_by,created_at) VALUES(?,?,?,?,?,?)',
                                (pid, title, steps, expected, user['id'], now()))
            return self.send_json({'id': cursor.lastrowid})
        check_id = ident(data, 'check_id')
        if not one(db, 'SELECT id FROM cases WHERE id=? AND project_id=?', (check_id, pid)):
            raise ValueError('Проверка не найдена в этой группе')
        status = data.get('status')
        if status not in STATUSES:
            raise ValueError('Выберите результат проверки')
        actual = optional(data, 'actual')
        # Добавляем результат отдельной строкой. Предыдущие строки сохраняются;
        # запрос выше показывает только последнюю для каждой проверки.
        db.execute('INSERT INTO runs(case_id,status,actual,executed_by,executed_at) VALUES(?,?,?,?,?)',
                   (check_id, status, actual, user['id'], now()))
        return self.send_json({'ok': True})

    def login_response(self, db, uid):
        """Создать сессию: токен отправить в cookie, в базе сохранить только его хеш."""
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        db.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                   (hashlib.sha256(token.encode()).hexdigest(), uid, csrf, int(time.time())+SESSION_AGE))
        user = one(db, 'SELECT id,name,email,role FROM users WHERE id=?', (uid,))
        return self.send_json({'user': user, 'csrf': csrf},
            cookies=[f'testlab_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_AGE}'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    init_db()
    httpd = ThreadingHTTPServer((args.host, args.port), App)
    print(f'ТестЛаб: http://{args.host}:{args.port}', flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
