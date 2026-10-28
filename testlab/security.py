"""Регистрация, вход и проверка сеанса."""

import hashlib
import re
import secrets
import time
from http.cookies import SimpleCookie

import bcrypt

from .config import SESSION_AGE
from .database import one, now
from .validation import text, RequestError

LOGIN_FAILURES = {}
COOKIE = 'testlab_session'
COOKIE_FLAGS = '; HttpOnly; SameSite=Strict; Path=/; Max-Age='


def token_hash(headers):
    cookies = SimpleCookie()
    try:
        cookies.load(headers.get('Cookie', ''))
    except Exception:
        return ''
    value = cookies.get(COOKIE)
    return hashlib.sha256(value.value.encode()).hexdigest() if value else ''


def authenticate(db, headers):
    return one(
        db,
        '''SELECT u.id,u.name,u.email,u.role,s.csrf
        FROM sessions s JOIN users u ON u.id=s.user_id
        WHERE s.token_hash=? AND s.expires_at>?''',
        (token_hash(headers), int(time.time())),
    )


def require_login(user):
    if not user:
        raise PermissionError('Войдите в аккаунт, чтобы продолжить')


def check_csrf(user, headers):
    require_login(user)
    if not secrets.compare_digest(headers.get('X-CSRF-Token', ''), user['csrf']):
        raise PermissionError('Сессия изменилась. Обновите страницу и войдите снова')
    if headers.get('Origin') and headers['Origin'] != 'http://' + headers.get(
        'Host', ''
    ):
        raise PermissionError('Недопустимый источник запроса')


def register(db, data):
    name, email = text(data, 'name', 80), text(data, 'email', 254).lower()
    password = text(data, 'password', 128)
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise ValueError('Введите корректную электронную почту')
    if len(password) < 10 or len(password.encode()) > 72:
        raise ValueError('Пароль должен содержать от 10 символов и не более 72 байт')
    return db.execute(
        'INSERT INTO users(name,email,password,role,created_at) VALUES(?,?,?,?,?)',
        (
            name,
            email,
            bcrypt.hashpw(password.encode(), bcrypt.gensalt()),
            'user',
            now(),
        ),
    ).lastrowid


def login(db, data):
    email, password = text(data, 'email', 254).lower(), text(data, 'password', 128)
    attempts = [t for t in LOGIN_FAILURES.get(email, []) if time.time() - t < 300]
    if len(attempts) >= 5:
        raise RequestError('Слишком много попыток. Повторите через 5 минут', 429)
    account = one(db, 'SELECT * FROM users WHERE email=?', (email,))
    if (
        not account
        or len(password.encode()) > 72
        or not bcrypt.checkpw(password.encode(), account['password'])
    ):
        LOGIN_FAILURES[email] = attempts + [time.time()]
        raise RequestError('Неверная почта или пароль', 401)
    LOGIN_FAILURES.pop(email, None)
    return account['id']


def create_session(db, uid):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    expires = int(time.time()) + SESSION_AGE
    hashed_token = hashlib.sha256(token.encode()).hexdigest()
    session = (hashed_token, uid, csrf, expires)
    db.execute('INSERT INTO sessions VALUES(?,?,?,?)', session)
    user = one(db, 'SELECT id,name,email,role FROM users WHERE id=?', (uid,))
    cookie = COOKIE + '=' + token + COOKIE_FLAGS + str(SESSION_AGE)
    return {'user': user, 'csrf': csrf}, [cookie]


def logout(db, headers):
    db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(headers),))
    return [COOKIE + '=' + COOKIE_FLAGS + '0']
