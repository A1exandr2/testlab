"""Проверка копий WAL-базы и команд чтения на временных данных."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class OperationsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'source.sqlite3'
        self.connection = sqlite3.connect(self.db, isolation_level=None)
        self.connection.executescript((ROOT / 'sql/schema.sql').read_text())
        self.connection.execute("INSERT INTO users VALUES (1,'Тест','test@example.test',X'00','user','2026-01-01')")

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def command(self, action, *, db=None, sql='', data=None):
        return subprocess.run(
            [sys.executable, str(ROOT / 'ops/manage.py'), action],
            env={**os.environ, 'TESTLAB_DB': str(db or self.db), 'SQL': sql},
            input=data, capture_output=True, timeout=60,
        )

    def test_backup_includes_committed_wal_and_import_preserves_it(self):
        self.assertTrue(Path(str(self.db) + '-wal').stat().st_size)
        backup = self.command('backup')
        self.assertEqual(backup.returncode, 0, backup.stderr)
        restored = Path(self.temp.name) / 'restored.sqlite3'
        result = self.command('import', db=restored, data=backup.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        with sqlite3.connect(restored) as db:
            self.assertEqual(db.execute('SELECT name FROM users').fetchone()[0], 'Тест')
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        before = restored.read_bytes()
        self.assertNotEqual(self.command('import', db=restored, data=backup.stdout).returncode, 0)
        self.assertEqual(before, restored.read_bytes())

    def test_query_reads_but_cannot_change_data(self):
        result = self.command('query', sql='SELECT name FROM users')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Тест', result.stdout.decode())
        self.assertNotEqual(self.command('query', sql='DELETE FROM users').returncode, 0)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)

    def test_invalid_import_leaves_destination_empty(self):
        destination = Path(self.temp.name) / 'invalid.sqlite3'
        result = self.command('import', db=destination, data=b'not a database')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
