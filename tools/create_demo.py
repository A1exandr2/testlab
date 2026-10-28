"""Создание учебной базы: python tools/create_demo.py [--db путь]."""

import argparse
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from testlab import database


def main():
    parser = argparse.ArgumentParser(description='Учебная база ТестЛаб')
    parser.add_argument(
        '--db', type=Path, default=ROOT / 'coursework/testlab_demo.sqlite3'
    )
    path = parser.parse_args().db
    if path.exists():
        parser.error('Файл уже существует. Укажите новый путь через --db.')
    database.DB = path
    database.init_db()
    with closing(database.connect()) as db:
        db.executescript((ROOT / 'coursework/demo.sql').read_text(encoding='utf-8'))
        tables = (
            'users',
            'sessions',
            'projects',
            'project_members',
            'cases',
            'runs',
            'app_settings',
        )
        counts = {
            table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            for table in tables
        }
        assert all(1 <= count <= 10 for count in counts.values()), counts
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    print(path)
    print(counts)


if __name__ == '__main__':
    main()
