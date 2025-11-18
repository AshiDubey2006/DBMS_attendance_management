"""
Uploads files under `uploads/` to a Supabase Storage bucket.

Requirements:
- `SUPABASE_URL`, `SUPABASE_KEY`, and `SUPABASE_PHOTO_BUCKET` (optional) in env or .env
- `supabase` Python package installed

Usage:
    python scripts/upload_uploads_to_supabase.py

This script will upload files to the configured bucket using the filename only. If a file already exists
it may fail — for idempotency you can rename or use a different bucket.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
BUCKET = os.getenv('SUPABASE_PHOTO_BUCKET', 'student_photos')
UPLOAD_DIR = Path('uploads')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("SUPABASE_URL and SUPABASE_KEY must be set in the environment (or .env)")
    raise SystemExit(1)

try:
    from supabase import create_client
except Exception as e:
    print('supabase package not installed. Install with `pip install supabase`')
    raise

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

if not UPLOAD_DIR.exists():
    print('No uploads directory found at', UPLOAD_DIR)
    raise SystemExit(0)

count = 0
for p in UPLOAD_DIR.rglob('*'):
    if p.is_file():
        remote_name = p.name
        try:
            with open(p, 'rb') as fd:
                data = fd.read()
            # upload may raise if file exists or permissions missing
            res = sb.storage.from_(BUCKET).upload(remote_name, data)
            print('Uploaded', p, '->', remote_name)
            count += 1
        except Exception as e:
            print('Failed to upload', p, e)

print(f'Done. Uploaded {count} files to Supabase Storage bucket "{BUCKET}".')
