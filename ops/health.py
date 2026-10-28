"""Проверка HTTP и обращения сервера к SQLite без входа в аккаунт."""
from http.client import HTTPConnection

connection = HTTPConnection('127.0.0.1', 8765, timeout=4)
try:
    connection.request('GET', '/api/me')
    response = connection.getresponse()
    response.read()
    # До отказа входа /api/me открывает базу и выполняет запрос sessions/users.
    raise SystemExit(0 if response.status == 403 else 1)
finally:
    connection.close()
