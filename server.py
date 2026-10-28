#!/usr/bin/env python3
"""Запуск: python server.py [--host 127.0.0.1] [--port 8765]."""

import argparse
from http.server import ThreadingHTTPServer

from testlab.database import init_db
from testlab.web import App


def main():
    parser = argparse.ArgumentParser(description='Локальный сервер ТестЛаб')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    init_db()
    with ThreadingHTTPServer((args.host, args.port), App) as server:
        print(f'ТестЛаб: http://{args.host}:{args.port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
