"""HTTP: файлы интерфейса, маршруты и ответы."""

import json
import mimetypes
import sqlite3
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from . import security, service
from .config import STATIC
from .database import connect
from .validation import RequestError

LOCK = threading.RLock()
FILES = {
    '/static/' + p.relative_to(STATIC).as_posix(): p
    for p in STATIC.rglob('*')
    if p.is_file()
}
FILES['/'] = STATIC / 'index.html'
ACTIONS = {
    '/api/projects': service.create_project,
    '/api/members': service.invite_member,
    '/api/checks': service.create_check,
    '/api/checks/result': service.save_result,
}


class App(BaseHTTPRequestHandler):
    server_version = 'TestLab/3.0'

    def send(self, raw, mime, status=200, cookies=()):
        self.send_response(status)
        headers = {
            'Content-Type': mime,
            'Content-Length': str(len(raw)),
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        }
        for key, value in headers.items():
            self.send_header(key, value)
        for cookie in cookies:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(raw)

    def send_json(self, obj, status=200, cookies=None):
        self.send(
            json.dumps(obj, ensure_ascii=False).encode(),
            'application/json; charset=utf-8',
            status,
            cookies or (),
        )

    def data(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 <= size <= 200_000:
                raise ValueError()
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeDecodeError):
            raise ValueError('Не удалось прочитать запрос') from None

    def dispatch(self, method):
        url = urlparse(self.path)
        if method == 'GET' and url.path in FILES:
            path = FILES[url.path]
            mime = mimetypes.guess_type(path)[0] or 'application/octet-stream'
            return self.send(path.read_bytes(), mime + '; charset=utf-8')
        try:
            if not url.path.startswith('/api/'):
                raise RequestError('Страница не найдена', 404)
            with LOCK, closing(connect()) as db:
                user = security.authenticate(db, self.headers)
                if method == 'GET':
                    security.require_login(user)
                    if url.path == '/api/me':
                        return self.send_json(
                            {
                                'user': {
                                    k: user[k] for k in ('id', 'name', 'email', 'role')
                                },
                                'csrf': user['csrf'],
                            }
                        )
                    if url.path == '/api/state':
                        project = parse_qs(url.query).get('project', [''])[0]
                        return self.send_json(service.get_state(db, user, project))
                else:
                    if (
                        self.headers.get('Content-Type', '').split(';')[0]
                        != 'application/json'
                    ):
                        raise ValueError('Не удалось прочитать запрос')
                    data = self.data()
                    if url.path in ('/api/login', '/api/register'):
                        action = (
                            security.login
                            if url.path.endswith('login')
                            else security.register
                        )
                        body, cookies = security.create_session(db, action(db, data))
                        return self.send_json(body, cookies=cookies)
                    security.check_csrf(user, self.headers)
                    if url.path == '/api/logout':
                        return self.send_json(
                            {'ok': True}, cookies=security.logout(db, self.headers)
                        )
                    if url.path in ACTIONS:
                        return self.send_json(ACTIONS[url.path](db, user, data))
                raise RequestError('Действие не найдено', 404)
        except (
            RequestError,
            ValueError,
            PermissionError,
            sqlite3.IntegrityError,
        ) as error:
            status, message = getattr(error, 'status', 400), str(error)
            if isinstance(error, PermissionError):
                status = 403
            if isinstance(error, sqlite3.IntegrityError):
                status, message = (
                    409,
                    'Такая запись уже существует. Проверьте введённые данные',
                )
            return self.send_json({'error': message}, status)

    def do_GET(self):
        self.dispatch('GET')

    def do_POST(self):
        self.dispatch('POST')
