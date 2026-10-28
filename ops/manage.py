"""Просмотр и резервное копирование SQLite. Основные команды вызываются Makefile."""
import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

DB = Path(os.environ.get('TESTLAB_DB', '/data/testlab.sqlite3'))


def connect():
    if not DB.is_file():
        raise SystemExit('База ещё не создана. Сначала выполните make up.')
    db = sqlite3.connect(DB.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
    db.execute('PRAGMA query_only=ON')
    return db


def show_rows(cursor):
    names = [column[0] for column in cursor.description or ()]
    rows = cursor.fetchmany(101)
    print(json.dumps([dict(zip(names, row)) for row in rows[:100]], ensure_ascii=False, indent=2, default=str))
    if len(rows) > 100:
        print('Показаны первые 100 строк.', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Данные ТестЛаб')
    parser.add_argument('action', choices=('db', 'tables', 'query', 'disk', 'backup', 'import'))
    action = parser.parse_args().action
    if action == 'disk':
        files = sorted(DB.parent.rglob('*'))
        for path in files:
            if path.is_file():
                print(f'{path.stat().st_size:>12,} байт  {path.relative_to(DB.parent)}')
        print(f'Всего: {sum(p.stat().st_size for p in files if p.is_file()):,} байт')
        return
    if action == 'import':
        if DB.exists():
            raise SystemExit('База уже существует. Импорт разрешён только в пустой том.')
        DB.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile() as incoming:
            while chunk := sys.stdin.buffer.read(1024 * 1024):
                incoming.write(chunk)
            incoming.flush()
            with sqlite3.connect(incoming.name) as source:
                if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise SystemExit('Входная база повреждена.')
                tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                required = {'users', 'sessions', 'projects', 'project_members', 'cases', 'runs', 'app_settings'}
                if not required <= tables:
                    raise SystemExit('Входной файл не является базой ТестЛаб.')
                # Готовый файл появляется целиком; существующую базу os.link не заменит.
                with tempfile.NamedTemporaryFile(dir=DB.parent) as prepared:
                    with sqlite3.connect(prepared.name) as destination:
                        source.backup(destination)
                    os.link(prepared.name, DB)
        print('База импортирована. Можно выполнить make up.')
        return
    with connect() as db:
        if action == 'tables':
            show_rows(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"))
        elif action == 'query':
            sql = os.environ.get('SQL', '').strip()
            if not sql:
                raise SystemExit('Укажите SQL: make query SQL="SELECT id,name FROM users"')
            show_rows(db.execute(sql))
        elif action == 'db':
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            for name in tables:
                safe_name = name.replace('"', '""')
                count = db.execute(f'SELECT COUNT(*) FROM "{safe_name}"').fetchone()[0]
                print(f'{name:<24} {count:>8} строк')
            print('Целостность:', db.execute('PRAGMA quick_check').fetchone()[0])
        elif action == 'backup':
            with tempfile.NamedTemporaryFile() as output:
                with sqlite3.connect(output.name) as destination:
                    db.backup(destination)
                sys.stdout.buffer.write(Path(output.name).read_bytes())


if __name__ == '__main__':
    try:
        main()
    except sqlite3.Error as error:
        raise SystemExit(f'Ошибка SQLite: {error}') from None
