"""Поддержка баз предыдущей версии, отдельно от рабочих операций."""

from .config import DEFAULT_ADMIN_EMAIL
from .database import one, rows, now


def migrate_roles(db):
    if one(db, "SELECT key FROM app_settings WHERE key='simple_roles'"):
        return
    db.execute('''INSERT OR IGNORE INTO project_members
        SELECT id,created_by,'member',created_at FROM projects''')
    if one(db, "SELECT name FROM sqlite_master WHERE type='table' AND name='invites'"):
        if 'project_id' in {c['name'] for c in rows(db, 'PRAGMA table_info(invites)')}:
            db.execute('''INSERT OR IGNORE INTO project_members
                SELECT project_id,used_by,'member',created_at FROM invites
                WHERE project_id IS NOT NULL AND used_by IS NOT NULL''')
    db.execute("UPDATE users SET role='user' WHERE role!='admin'")
    db.execute("UPDATE project_members SET role='member' WHERE role!='admin'")
    db.execute("INSERT INTO app_settings VALUES('simple_roles','1')")


def correct_admin_roles(db, admin_id):
    if one(db, "SELECT key FROM app_settings WHERE key='account_roles_v2'"):
        return
    db.execute("UPDATE users SET role='user' WHERE email!=?", (DEFAULT_ADMIN_EMAIL,))
    db.execute(
        "UPDATE project_members SET role='member' WHERE user_id IN (SELECT id FROM users WHERE role!='admin')"
    )
    db.execute(
        '''INSERT OR IGNORE INTO project_members
        SELECT p.id,?,'admin',? FROM projects p WHERE NOT EXISTS (
            SELECT 1 FROM project_members m JOIN users u ON u.id=m.user_id
            WHERE m.project_id=p.id AND u.role='admin')''',
        (admin_id, now()),
    )
    db.execute("UPDATE project_members SET role='admin' WHERE user_id=?", (admin_id,))
    db.execute("INSERT INTO app_settings VALUES('account_roles_v2','1')")
