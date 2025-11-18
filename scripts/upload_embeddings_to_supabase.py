"""
Uploads local NumPy embedding files from `data/embeddings/*.npy` to Supabase table `face_embeddings`.

Requirements:
- Set `SUPABASE_URL` and `SUPABASE_KEY` in the environment or in a `.env` file.
- The Supabase table `face_embeddings` should exist with columns: `student_id int primary key`, `embedding jsonb`.

Usage:
    python scripts/upload_embeddings_to_supabase.py

This script will upsert each embedding using `student_id` as the key.
"""
import os
import json
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
EMB_DIR = Path('data/embeddings')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("SUPABASE_URL and SUPABASE_KEY must be set in the environment (or .env)")
    raise SystemExit(1)

try:
    from supabase import create_client
except Exception as e:
    print('supabase package not installed. Install with `pip install supabase`')
    raise

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

files = list(EMB_DIR.glob('*.npy'))
if not files:
    print('No embeddings found in', EMB_DIR)
    raise SystemExit(0)

import numpy as np

count = 0
for f in files:
    try:
        sid = int(f.stem)
    except Exception:
        print('Skipping non-numeric file', f)
        continue
    try:
        emb = np.load(f)
    except Exception as e:
        print('Failed to load', f, e)
        continue
    payload = {'student_id': sid, 'embedding': emb.tolist()}
    try:
        # Upsert by primary key student_id
        resp = sb.table('face_embeddings').upsert(payload).execute()
        print('Upserted', sid)
        count += 1
    except Exception as e:
        print('Failed to upsert', sid, e)

print(f'Done. Upserted {count} embeddings to Supabase (table: face_embeddings).')
