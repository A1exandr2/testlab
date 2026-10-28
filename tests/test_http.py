"""Проверка настоящего HTTP-сервера на отдельной временной базе."""
import http.client
import json
import re
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path

from testlab import database, security
from testlab.web import App


class QuietApp(App):
    def log_message(self, *args):
        pass


class Client:
    def __init__(self, address):
        self.address, self.cookie, self.csrf = address, '', ''

    def request(self, path, data=None, *, raw=None, headers=None):
        values = {'Cookie': self.cookie}
        body = raw
        if data is not None:
            body = json.dumps(data).encode()
        if body is not None:
            values.update({'Content-Type': 'application/json', 'X-CSRF-Token': self.csrf})
        values.update(headers or {})
        with closing(http.client.HTTPConnection(*self.address, timeout=5)) as conn:
            conn.request('POST' if body is not None else 'GET', path, body, values)
            response = conn.getresponse()
            result = response.read()
            cookie = response.getheader('Set-Cookie')
            if cookie:
                self.cookie = cookie.split(';')[0]
            if response.getheader('Content-Type', '').startswith('application/json'):
                result = json.loads(result)
                self.csrf = result.get('csrf', self.csrf)
            return response.status, result, dict(response.getheaders())

    def register(self, name):
        return self.request('/api/register', {'name': name, 'email': name+'@example.test', 'password': 'User12345!'})


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = database.DB
        database.DB = Path(self.temp.name) / 'http.sqlite3'
        security.LOGIN_FAILURES.clear()
        database.init_db()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), QuietApp)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = Client(self.server.server_address)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        database.DB = self.original
        self.temp.cleanup()

    def test_every_static_asset_and_private_paths(self):
        status, page, headers = self.client.request('/')
        self.assertEqual(status, 200)
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        paths = re.findall(r'(?:src|href)="([^"]+)"', page.decode())
        self.assertEqual(len(paths), 10)
        for path in paths:
            status, body, headers = self.client.request(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(body, path)
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
            if path.endswith('.js'):
                self.assertIn('javascript', headers['Content-Type'])
            if path.endswith('.css'):
                self.assertIn('text/css', headers['Content-Type'])
        for path in ('/server.py', '/sql/schema.sql', '/testlab.sqlite3', '/static/../server.py'):
            self.assertEqual(self.client.request(path)[0], 404, path)

    def test_malformed_requests(self):
        for raw in (b'{', b'[]', b'null', b'\xff'):
            self.assertEqual(self.client.request('/api/login', raw=raw)[0], 400)
        self.assertEqual(self.client.request('/api/login', raw=b'{}', headers={'Content-Type':'text/plain'})[0], 400)
        self.assertEqual(self.client.request('/api/login', raw=b'', headers={'Content-Length':'200001'})[0], 400)
        self.assertEqual(self.client.request('/api/me')[0], 403)

    def test_two_users_collaborate_over_http(self):
        owner, member, outsider = [Client(self.server.server_address) for _ in range(3)]
        for client, name in ((owner,'owner'), (member,'member'), (outsider,'outsider')):
            self.assertEqual(client.register(name)[0], 200)
        status, body, _ = owner.request('/api/projects', {'name':'Общая работа'})
        self.assertEqual(status, 200)
        pid = body['id']
        self.assertEqual(owner.request('/api/members', {'project_id':pid,'email':'member@example.test'})[0], 200)
        status, body, _ = member.request('/api/checks', {'project_id':pid,'title':'Вход','steps':'Войти','expected':'Обзор'})
        self.assertEqual(status, 200)
        cid = body['id']
        for result in ('failed', 'passed'):
            self.assertEqual(owner.request('/api/checks/result', {'project_id':pid,'check_id':cid,'status':result})[0], 200)
        state = member.request('/api/state?project='+str(pid))[1]
        self.assertEqual(state['metrics']['passed'], 1)
        self.assertEqual(state['checks'][0]['status'], 'passed')
        self.assertEqual(outsider.request('/api/state?project='+str(pid))[0], 403)
        self.assertEqual(member.request('/api/logout', {})[0], 200)
        self.assertEqual(member.request('/api/me')[0], 403)
        self.assertEqual(owner.request('/api/me')[0], 200)

    def test_csrf_origin_cookie_and_expiration(self):
        status, _, headers = self.client.register('security')
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertEqual(self.client.request('/api/projects', {'name':'Без токена'}, headers={'X-CSRF-Token':''})[0], 403)
        self.assertEqual(self.client.request('/api/projects', {'name':'Другой сайт'}, headers={'Origin':'http://other.test'})[0], 403)
        with closing(database.connect()) as db:
            db.execute('UPDATE sessions SET expires_at=1')
        self.assertEqual(self.client.request('/api/me')[0], 403)
        self.client.cookie = 'testlab_session=invalid'
        self.assertEqual(self.client.request('/api/me')[0], 403)

    def test_failed_membership_rolls_back_project(self):
        self.client.register('rollback')
        with closing(database.connect()) as db:
            before = db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
            db.execute("""CREATE TRIGGER reject_member BEFORE INSERT ON project_members
                BEGIN SELECT RAISE(ABORT, 'test rollback'); END""")
        self.assertEqual(self.client.request('/api/projects', {'name':'Откат'})[0], 409)
        with closing(database.connect()) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM projects').fetchone()[0], before)
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
