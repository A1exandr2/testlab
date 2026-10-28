"""API workflow with independent browser sessions, without binding a socket."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import bcrypt
import server


class Browser:
    def __init__(self):
        self.cookie = ''
        self.csrf = ''

    def call(self, path, data=None, token=True):
        handler = server.App.__new__(server.App)
        handler.path = '/api/' + path
        handler.headers = {'Cookie': self.cookie, 'Host': '127.0.0.1:8765'}
        result = {}

        def send_json(body, status=200, cookies=None):
            result.update(status=status, body=body)
            if cookies:
                self.cookie = cookies[0].split(';')[0]

        handler.send_json = send_json
        if data is not None:
            handler.headers['Content-Type'] = 'application/json'
            handler.data = lambda: data
            if token:
                handler.headers['X-CSRF-Token'] = self.csrf
        handler.dispatch('POST' if data is not None else 'GET')
        if path in ('register', 'login') and result['status'] == 200:
            self.csrf = result['body']['csrf']
        return result['status'], result['body']

    def register(self, email='user@example.test', name='Пользователь'):
        return self.call('register', {'name': name, 'email': email, 'password': 'User12345!'})

    def login_admin(self):
        return self.call('login', {'email': server.DEFAULT_ADMIN_EMAIL, 'password': server.DEFAULT_ADMIN_PASSWORD})


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = server.DB
        server.DB = Path(self.temp.name) / 'testlab.sqlite3'
        server.LOGIN_FAILURES.clear()
        server.init_db()

    def tearDown(self):
        server.DB = self.original_db
        self.temp.cleanup()

    def setup_team(self):
        admin, member = Browser(), Browser()
        self.assertEqual(admin.login_admin()[0], 200)
        self.assertEqual(member.register()[0], 200)
        pid = admin.call('state')[1]['project_id']
        self.assertEqual(admin.call('members', {'project_id': pid, 'email': 'user@example.test'})[0], 200)
        return admin, member, pid

    def test_two_windows_share_checks_results_and_summary(self):
        admin, member, pid = self.setup_team()
        check_data = {'project_id': pid, 'title': 'Вход пользователя',
                      'steps': 'Открыть приложение. Войти.', 'expected': 'Открыт обзор.'}
        status, body = member.call('checks', check_data)
        self.assertEqual(status, 200, body)
        cid = body['id']
        state = admin.call('state')[1]
        self.assertEqual(state['metrics'], {'total': 1, 'not_run': 1, 'passed': 0, 'failed': 0, 'blocked': 0})
        self.assertEqual(state['checks'][0]['title'], check_data['title'])
        for result in ['failed', 'blocked', 'passed', 'not_run']:
            writer, reader = (member, admin) if result in ('failed', 'passed') else (admin, member)
            self.assertEqual(writer.call('checks/result', {
                'project_id': pid, 'check_id': cid, 'status': result, 'actual': 'Комментарий: '+result
            })[0], 200)
            state = reader.call('state')[1]
            self.assertEqual(state['checks'][0]['status'], result)
            self.assertEqual(state['checks'][0]['actual'], 'Комментарий: '+result)
            self.assertEqual(state['metrics'][result], 1)
            self.assertEqual(sum(state['metrics'][s] for s in server.STATUSES), 1)
        self.assertEqual(member.call('logout', {})[0], 200)
        self.assertEqual(member.call('state')[0], 403)
        self.assertEqual(admin.call('state')[0], 200)

    def test_admin_rights_memberships_and_retired_actions(self):
        admin, member = Browser(), Browser()
        self.assertEqual(member.call('state')[0], 403)
        self.assertEqual(admin.login_admin()[1]['user']['role'], 'admin')
        self.assertEqual(member.call('register', {
            'name': 'Пользователь', 'email': 'user@example.test',
            'password': 'User12345!', 'role': 'admin'
        })[1]['user']['role'], 'user')
        pid = admin.call('state')[1]['project_id']
        self.assertEqual(member.call('state')[1]['projects'], [])
        self.assertEqual(member.call(f'state?project={pid}')[0], 403)
        self.assertEqual(member.call('projects', {'name': 'Группа пользователя'})[0], 200)
        self.assertEqual(member.call('me')[1]['user']['role'], 'user')
        self.assertEqual(member.call('projects', {'name': 'Без CSRF'}, token=False)[0], 403)
        self.assertEqual(admin.call('projects', {'name': 'Группа'}, token=False)[0], 403)
        self.assertEqual(member.call('checks', {'project_id': pid, 'title': 'Чужая проверка'})[0], 403)
        self.assertEqual(admin.call('members', {'project_id': pid, 'email': 'missing@example.test'})[0], 400)
        self.assertEqual(admin.call('members', {'project_id': pid, 'email': 'user@example.test'})[0], 200)
        self.assertEqual(admin.call('members', {'project_id': pid, 'email': 'user@example.test'})[0], 400)
        self.assertEqual(member.call('state')[1]['project_role'], 'member')
        self.assertEqual(member.call('members', {'project_id': pid, 'email': 'other@example.test'})[0], 400)
        self.assertEqual(member.call('checks', {'project_id': pid, 'title': 'Без CSRF'}, token=False)[0], 403)
        for path in ['requirements', 'plans', 'plans/status', 'cases', 'runs', 'defects', 'defects/status']:
            self.assertEqual(admin.call(path, {'project_id': pid})[0], 404, path)

    def test_groups_are_isolated_even_for_another_admin(self):
        admin, member, pid = self.setup_team()
        private = admin.call('projects', {'name': 'Закрытая группа'})[1]['id']
        check = admin.call('checks', {'project_id': private, 'title': 'Закрытая проверка',
                                     'steps': 'Шаг', 'expected': 'Результат'})[1]['id']
        self.assertEqual(member.call(f'state?project={private}')[0], 403)
        self.assertEqual(member.call('checks/result', {'project_id': pid, 'check_id': check, 'status': 'passed'})[0], 400)
        self.assertEqual(member.call('state')[1]['checks'], [])
        with server.connect() as db:
            db.execute("UPDATE users SET role='admin' WHERE email='user@example.test'")
        self.assertEqual(member.call(f'state?project={private}')[0], 403)
        self.assertEqual(member.call('projects', {'name': 'Личная группа второго администратора'})[0], 200)
        self.assertEqual(len(admin.call('state')[1]['projects']), 2)

    def test_initialization_is_idempotent_and_keeps_existing_data(self):
        admin, member, pid = self.setup_team()
        cid = member.call('checks', {'project_id': pid, 'title': 'Сохранённая проверка',
                                    'steps': 'Шаги', 'expected': 'Ожидание'})[1]['id']
        db = server.connect()
        before = {table: db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                  for table in ['users', 'projects', 'project_members', 'cases', 'runs']}
        new_hash = bcrypt.hashpw(b'Changed12345!', bcrypt.gensalt())
        db.execute('UPDATE users SET password=? WHERE email=?', (new_hash, server.DEFAULT_ADMIN_EMAIL))
        db.close()
        server.init_db()
        db = server.connect()
        after = {table: db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in before}
        self.assertEqual(before, after)
        self.assertEqual(db.execute('SELECT password FROM users WHERE email=?', (server.DEFAULT_ADMIN_EMAIL,)).fetchone()[0], new_hash)
        self.assertEqual(db.execute('SELECT title FROM cases WHERE id=?', (cid,)).fetchone()[0], 'Сохранённая проверка')
        db.close()

    def test_upgrade_preserves_owners_members_and_legacy_data(self):
        old = sqlite3.connect(server.DB)
        old.executescript('''
            DELETE FROM app_settings WHERE key='simple_roles';
            DELETE FROM app_settings WHERE key='account_roles_v2';
            INSERT INTO users VALUES(100,'Старый владелец','old@example.test',X'00','user','2026-01-01');
            INSERT INTO users VALUES(101,'Разработчик','dev@example.test',X'00','developer','2026-01-01');
            INSERT INTO users VALUES(102,'Наблюдатель','view@example.test',X'00','viewer','2026-01-01');
            INSERT INTO projects VALUES(100,'Старая группа','Описание',100,'2026-01-01');
            INSERT INTO project_members VALUES(100,101,'developer','2026-01-01');
            INSERT INTO project_members VALUES(100,102,'viewer','2026-01-01');
            CREATE TABLE requirements(id INTEGER PRIMARY KEY,title TEXT);
            INSERT INTO requirements VALUES(1,'Старое требование');
            INSERT INTO cases(id,project_id,title,steps,expected,created_by,created_at)
                VALUES(100,100,'Старый кейс','Шаги','Результат',100,'2026-01-01');
            INSERT INTO runs(case_id,status,actual,executed_by,executed_at)
                VALUES(100,'failed','Ошибка',101,'2026-01-01');
        ''')
        old.close()
        server.init_db()
        db = server.connect()
        self.assertEqual(db.execute('SELECT role FROM users WHERE id=100').fetchone()[0], 'user')
        self.assertEqual(db.execute('SELECT role FROM project_members WHERE user_id=100').fetchone()[0], 'member')
        self.assertEqual(db.execute('SELECT role FROM project_members WHERE user_id=101').fetchone()[0], 'member')
        self.assertEqual(db.execute('SELECT role FROM project_members WHERE user_id=102').fetchone()[0], 'member')
        self.assertEqual(db.execute('SELECT title FROM requirements').fetchone()[0], 'Старое требование')
        self.assertEqual(db.execute('SELECT title FROM cases WHERE id=100').fetchone()[0], 'Старый кейс')
        self.assertEqual(db.execute('SELECT status FROM runs WHERE case_id=100').fetchone()[0], 'failed')
        db.close()

    def test_accidental_legacy_admin_is_corrected_in_existing_session(self):
        admin, member, pid = self.setup_team()
        with server.connect() as db:
            uid = db.execute("SELECT id FROM users WHERE email='user@example.test'").fetchone()[0]
            db.execute("UPDATE users SET role='admin' WHERE id=?", (uid,))
            group = db.execute('INSERT INTO projects(name,created_by,created_at) VALUES(?,?,?)',
                               ('Старая группа', uid, server.now())).lastrowid
            db.execute('INSERT INTO project_members VALUES(?,?,?,?)', (group, uid, 'admin', server.now()))
            db.execute("DELETE FROM app_settings WHERE key='account_roles_v2'")
        self.assertEqual(member.call('me')[1]['user']['role'], 'admin')
        server.init_db()
        state = member.call(f'state?project={group}')[1]
        self.assertEqual(state['user']['role'], 'user')
        self.assertEqual(state['project_role'], 'member')
        self.assertEqual(next(u['role'] for u in state['users'] if u['id'] == uid), 'member')
        self.assertEqual(member.call('projects', {'name': 'Своя группа'})[0], 200)
        self.assertEqual(member.call('me')[1]['user']['role'], 'user')
        self.assertEqual(member.call('members', {'project_id': group, 'email': server.DEFAULT_ADMIN_EMAIL})[0], 400)
        self.assertEqual(admin.call(f'state?project={group}')[1]['project_role'], 'admin')
        # A stale legacy membership must never grant account-level admin rights.
        with server.connect() as db:
            db.execute("UPDATE project_members SET role='admin' WHERE user_id=?", (uid,))
        self.assertEqual(member.call(f'state?project={group}')[1]['project_role'], 'member')
        self.assertEqual(member.call('members', {'project_id': group, 'email': 'missing@example.test'})[0], 400)

    def test_regular_users_can_create_group_invite_and_collaborate(self):
        owner, participant, colleague, outsider = [Browser() for _ in range(4)]
        for browser,email in [(owner,'owner@example.test'),(participant,'participant@example.test'),
                              (colleague,'colleague@example.test'),(outsider,'outsider@example.test')]:
            self.assertEqual(browser.register(email)[0], 200)
        status,body = owner.call('projects', {'name': 'Группа без администратора'})
        self.assertEqual(status, 200, body)
        pid = body['id']
        self.assertEqual(owner.call(f'state?project={pid}')[1]['project_role'], 'member')
        self.assertEqual(participant.call('members', {'project_id':pid,'email':'outsider@example.test'})[0], 403)
        self.assertEqual(owner.call('members', {'project_id':pid,'email':'participant@example.test'})[0], 200)
        # An invited ordinary member can invite the next participant as well.
        self.assertEqual(participant.call('members', {'project_id':pid,'email':'colleague@example.test'})[0], 200)
        status,body = participant.call('checks', {'project_id':pid,'title':'Общая проверка',
                                                 'steps':'Выполнить шаг','expected':'Получить результат'})
        self.assertEqual(status, 200, body)
        cid=body['id']
        self.assertEqual(owner.call(f'state?project={pid}')[1]['checks'][0]['id'], cid)
        self.assertEqual(colleague.call('checks/result', {'project_id':pid,'check_id':cid,
                                                        'status':'passed','actual':'Готово'})[0], 200)
        self.assertEqual(owner.call(f'state?project={pid}')[1]['metrics']['passed'], 1)
        self.assertEqual(participant.call(f'state?project={pid}')[1]['checks'][0]['actual'], 'Готово')
        for browser in [owner,participant,colleague]:
            self.assertEqual(browser.call('me')[1]['user']['role'], 'user')
        self.assertEqual(outsider.call(f'state?project={pid}')[0], 403)
        self.assertEqual(outsider.call('checks/result', {'project_id':pid,'check_id':cid,'status':'failed'})[0], 403)
        self.assertEqual(outsider.call('members', {'project_id':pid,'email':'outsider@example.test'})[0], 403)

    def test_validation_and_login_throttle(self):
        admin, member, pid = self.setup_team()
        self.assertEqual(member.register()[0], 409)
        self.assertEqual(Browser().call('register', {'name': 'Кто-то', 'email': 'bad', 'password': 'User12345!'})[0], 400)
        self.assertEqual(Browser().call('register', {'name': 'Кто-то', 'email': 'new@example.test', 'password': 'я'*40})[0], 400)
        self.assertEqual(member.call('checks', {'project_id': pid, 'title': 'Проверка', 'steps': '', 'expected': 'Да'})[0], 400)
        cid = member.call('checks', {'project_id': pid, 'title': 'Проверка', 'steps': 'Шаги', 'expected': 'Да'})[1]['id']
        self.assertEqual(member.call('checks/result', {'project_id': pid, 'check_id': cid, 'status': 'unknown'})[0], 400)
        self.assertEqual(member.call('checks/result', {'project_id': pid, 'check_id': cid, 'status': 'passed', 'actual': []})[0], 400)
        other_session = Browser()
        for _ in range(5):
            self.assertEqual(other_session.call('login', {'email': 'user@example.test', 'password': 'wrong password'})[0], 401)
        self.assertEqual(other_session.call('login', {'email': 'user@example.test', 'password': 'User12345!'})[0], 429)
        self.assertEqual(admin.call('state')[0], 200)


if __name__ == '__main__':
    unittest.main()
