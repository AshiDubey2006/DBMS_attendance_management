"""Simple migration helper: SQLite -> Postgres (Supabase)

Usage:
1. Install deps: `pip install sqlalchemy psycopg2-binary python-dotenv`
2. Set `TARGET_DATABASE_URL` env var to your Supabase connection string, or put it in a `.env` file.
3. Run: `python scripts/migrate_sqlite_to_postgres.py --sqlite path/to/attendance.db`

Notes:
- This script does a naive row-by-row copy for all tables present in the SQLite DB.
- It does not handle complex migrations such as sequences, triggers, foreign key order — use with care on small DBs.
- For production or large DBs, prefer `pgloader` or a controlled dump/restore process.
"""
import os
import argparse
from sqlalchemy import create_engine, MetaData, Table, select, insert
from sqlalchemy.exc import SQLAlchemyError
import importlib

# Load .env when available (use dynamic import to avoid hard dependency)
try:
    dotenv_mod = importlib.import_module('dotenv')
    load_dotenv = getattr(dotenv_mod, 'load_dotenv', lambda: None)
except Exception:
    def load_dotenv():
        return None

load_dotenv()

def copy_db(sqlite_url: str, target_url: str):
    src_engine = create_engine(sqlite_url)
    tgt_engine = create_engine(target_url)

    src_meta = MetaData()
    tgt_meta = MetaData()

    src_meta.reflect(bind=src_engine)
    tgt_meta.reflect(bind=tgt_engine)

    # Create tables on target that don't exist yet (use SQLite DDL reflected names)
    for tbl in src_meta.sorted_tables:
        if tbl.name not in tgt_meta.tables:
            print(f"Creating missing table on target: {tbl.name}")
            tbl.metadata = tgt_meta
            tbl.create(bind=tgt_engine)

    # Refresh target metadata
    tgt_meta.reflect(bind=tgt_engine)

    # Copy table data in a safe order: try to respect foreign-key dependency by table order
    for tbl in src_meta.sorted_tables:
        print(f"Copying table: {tbl.name}")
        tgt_tbl = Table(tbl.name, tgt_meta, autoload_with=tgt_engine)
        conn_src = src_engine.connect()
        conn_tgt = tgt_engine.connect()
        try:
            rows = conn_src.execute(select(tbl)).fetchall()
            if not rows:
                print("  (no rows)")
                continue
            # Insert in batches
            batch = []
            for row in rows:
                batch.append(dict(row._mapping))
                if len(batch) >= 200:
                    conn_tgt.execute(insert(tgt_tbl), batch)
                    batch = []
            if batch:
                conn_tgt.execute(insert(tgt_tbl), batch)
            print(f"  inserted {len(rows)} rows")
        except SQLAlchemyError as e:
            print(f"  ERROR copying {tbl.name}: {e}")
        finally:
            conn_src.close()
            conn_tgt.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--sqlite', default='attendance.db', help='Path to SQLite DB file')
    p.add_argument('--target', default=os.getenv('TARGET_DATABASE_URL') or os.getenv('DATABASE_URL'), help='Target DB URL (Postgres)')
    args = p.parse_args()

    sqlite_url = f"sqlite:///{args.sqlite}"
    target_url = args.target
    if not target_url:
        print('Missing target DB URL. Set TARGET_DATABASE_URL or DATABASE_URL env var or pass --target')
        raise SystemExit(1)

    # Convert postgres:// -> postgresql+psycopg2:// if necessary
    if target_url.startswith('postgres://'):
        target_url = target_url.replace('postgres://', 'postgresql+psycopg2://', 1)

    print('Source:', sqlite_url)
    print('Target:', target_url)
    copy_db(sqlite_url, target_url)
