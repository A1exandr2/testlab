"""Группы, участники, проверки и результаты."""

from .config import STATUSES
from .database import one, rows, now
from .validation import ident, text


def project_role(db, user, pid):
    if not one(
        db,
        'SELECT user_id FROM project_members WHERE project_id=? AND user_id=?',
        (pid, user['id']),
    ):
        raise PermissionError('Нет доступа к этой группе')
    return 'admin' if user['role'] == 'admin' else 'member'


def add_member(db, pid, account):
    role = 'admin' if account['role'] == 'admin' else 'member'
    db.execute(
        'INSERT INTO project_members VALUES(?,?,?,?)', (pid, account['id'], role, now())
    )


def create_project(db, user, data):
    title = text(data, 'name', 100)
    with db:
        db.execute('BEGIN IMMEDIATE')
        pid = db.execute(
            '''INSERT INTO projects(name,created_by,created_at)
            VALUES(?,?,?)''',
            (title, user['id'], now()),
        ).lastrowid
        add_member(db, pid, user)
    return {'id': pid}


def invite_member(db, user, data):
    pid = ident(data, 'project_id')
    project_role(db, user, pid)
    email = text(data, 'email', 254).lower()
    account = one(db, 'SELECT id,role FROM users WHERE email=?', (email,))
    if not account:
        raise ValueError(
            'Пользователь ещё не зарегистрирован. Попросите его создать аккаунт'
        )
    if one(
        db,
        'SELECT user_id FROM project_members WHERE project_id=? AND user_id=?',
        (pid, account['id']),
    ):
        raise ValueError('Пользователь уже состоит в этой группе')
    add_member(db, pid, account)
    return {'ok': True}


def create_check(db, user, data):
    pid = ident(data, 'project_id')
    project_role(db, user, pid)
    fields = [
        text(data, 'title'),
        text(data, 'steps', 5000),
        text(data, 'expected', 5000),
    ]
    cid = db.execute(
        '''INSERT INTO cases(
            project_id,title,steps,expected,created_by,created_at)
        VALUES(?,?,?,?,?,?)''',
        (pid, *fields, user['id'], now()),
    ).lastrowid
    return {'id': cid}


def save_result(db, user, data):
    pid, cid = ident(data, 'project_id'), ident(data, 'check_id')
    project_role(db, user, pid)
    if not one(db, 'SELECT id FROM cases WHERE id=? AND project_id=?', (cid, pid)):
        raise ValueError('Проверка не найдена в этой группе')
    status = data.get('status')
    if status not in STATUSES:
        raise ValueError('Выберите результат проверки')
    actual = text(data, 'actual', 5000, required=False)
    db.execute(
        '''INSERT INTO runs(case_id,status,actual,executed_by,executed_at)
        VALUES(?,?,?,?,?)''',
        (cid, status, actual, user['id'], now()),
    )
    return {'ok': True}


def get_state(db, user, project=''):
    projects = rows(
        db,
        '''SELECT p.id,p.name FROM projects p JOIN project_members m
        ON m.project_id=p.id WHERE m.user_id=? ORDER BY p.name COLLATE NOCASE,p.id''',
        (user['id'],),
    )
    pid = (
        ident({'id': project}, 'id')
        if project
        else (projects[0]['id'] if projects else None)
    )
    role = project_role(db, user, pid) if pid else None
    members, checks = [], []
    if pid:
        members = rows(
            db,
            '''SELECT u.id,u.name,u.email,
            CASE WHEN u.role='admin' THEN 'admin' ELSE 'member' END AS role,m.joined_at
            FROM users u JOIN project_members m ON m.user_id=u.id
            WHERE m.project_id=? ORDER BY u.name,u.id''',
            (pid,),
        )
        checks = rows(
            db,
            '''SELECT c.id,c.title,c.steps,c.expected,c.preconditions,c.created_at,
            u.name AS creator,COALESCE(r.status,'not_run') AS status,COALESCE(r.actual,'') AS actual,
            r.executed_at AS updated_at,e.name AS updated_by
            FROM cases c JOIN users u ON u.id=c.created_by
            LEFT JOIN runs r ON r.id=(
                SELECT MAX(id) FROM runs WHERE case_id=c.id
            )
            LEFT JOIN users e ON e.id=r.executed_by
            WHERE c.project_id=? ORDER BY c.id DESC''',
            (pid,),
        )
    metrics = {
        status: sum(c['status'] == status for c in checks) for status in STATUSES
    }
    return {
        'user': {k: user[k] for k in ('id', 'name', 'email', 'role')},
        'projects': projects,
        'project_id': pid,
        'project_role': role,
        'users': members,
        'checks': checks,
        'metrics': {'total': len(checks), **metrics},
    }
