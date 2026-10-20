"""User-run output export. Never run against real data from an AI agent session."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export your own output schema using local .env credentials.")
    parser.add_argument('--schema', default='c1_output', help='Your exact output schema (default: c1_output).')
    parser.add_argument('--env-prefix', default='APP_DB_PFOI', help='Prefix for your USER/PASSWORD settings (default: APP_DB_PFOI).')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'c[1-9][0-9]*_output', args.schema):
        parser.error('--schema must be your cN_output schema.')
    if not re.fullmatch(r'APP_DB_[A-Z0-9]+', args.env_prefix):
        parser.error('--env-prefix must have the form APP_DB_PFOI or APP_DB_C2.')
    executable = shutil.which('pg_dump')
    if not executable:
        print('Install PostgreSQL command-line tools and add pg_dump to PATH.')
        return 1
    try:
        from dotenv import dotenv_values
    except ImportError:
        print('Install project dependencies: python -m pip install -r backend/requirements.txt')
        return 1
    # Explicitly disable interpolation so password characters remain literal.
    settings = dict(dotenv_values(REPO_ROOT / '.env', interpolate=False))
    settings.update(os.environ)
    user = settings.get(args.env_prefix + '_USER')
    password = settings.get(args.env_prefix + '_PASSWORD')
    if not user or not password:
        print(f'Set {args.env_prefix}_USER and {args.env_prefix}_PASSWORD in your local .env.')
        return 1
    try:
        port = int(settings.get('APP_DB_PORT') or '5433')
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        print('APP_DB_PORT must be a valid port number.')
        return 1
    folder = REPO_ROOT / 'component_exports'
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = folder / f'{args.schema}_{stamp}.dump'
    command = [executable, '-h', settings.get('APP_DB_HOST') or 'localhost',
               '-p', str(port), '-U', user, '-d', settings.get('APP_DB_NAME') or 'farmx_app',
               '--schema=' + args.schema, '-Fc', '--no-owner', '--no-privileges',
               '--strict-names', '--no-password', '-f', str(output)]
    child_env = os.environ.copy()
    child_env['PGPASSWORD'] = password
    # Do not expose database diagnostics, credentials or output contents in the console.
    try:
        result = subprocess.run(command, env=child_env, capture_output=True, check=False)
    except OSError:
        print('Could not start pg_dump. Check the local PostgreSQL tools installation.')
        return 1
    if result.returncode:
        print('Export failed. Check your local database, credentials and schema permissions.')
        print('Any dump file from this failed attempt is incomplete; do not share it.')
        return 1
    print(f'Export saved: {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
