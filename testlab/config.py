"""Пути и общие значения."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'static'
SCHEMA = ROOT / 'sql' / 'schema.sql'
DEFAULT_ADMIN_EMAIL = 'admin@testlab.local'
DEFAULT_ADMIN_PASSWORD = 'Admin12345!'
SESSION_AGE = 12 * 3600
STATUSES = ('not_run', 'passed', 'failed', 'blocked')
