Supabase setup and migration

Overview
- Use Supabase (managed Postgres + storage) to centralize your app database and uploaded files (photos/embeddings).

1) Create a Supabase project
- Go to https://app.supabase.com and create a free project.
- Choose a strong password for the database and remember the project region.

2) Get the Postgres connection string
- In the Supabase project dashboard go to Settings → Database → Connection Pooling / Connection string.
- Copy the connection string. It may look like:
  postgres://user:password@db.host.supabase.co:5432/postgres

3) Set the DATABASE_URL for your app
- On your local machine (PowerShell) you can set it temporarily before running:

```powershell
$env:DATABASE_URL = 'postgresql+psycopg2://user:password@db.host.supabase.co:5432/postgres'
python app.py
```

- If Supabase gave you a string starting with `postgres://`, the app will auto-convert it to `postgresql+psycopg2://`.
- For deployment, set `DATABASE_URL` in your host config (Supabase Edge Functions, Railway, Heroku, or CI/CD secrets).

4) Expose uploads and embeddings
- Supabase Storage: create a bucket (e.g., `uploads`) and enable public or signed URL access depending on your privacy needs.
- Upload existing files from `uploads/` and `data/embeddings/` into the storage bucket. Store the public URL or storage path in the `photo_path` column or in an `embeddings` table.

Recommended schema for embeddings (optional improvement)
- Add a database table `face_embeddings` with columns: `student_id INTEGER PRIMARY KEY`, `embedding BYTEA` or `embedding REAL[]`.
- When enrolling a student, save the embedding into that table instead of only writing `data/embeddings/<id>.npy`.
- Modify `FaceService` to read embeddings from the DB at startup or on demand.

5) Migrate data from local SQLite
Options:
- Quick (external tool): Use `pgloader` to migrate SQLite to Postgres (recommended for fidelity).
- Scripted: Use the included `scripts/migrate_sqlite_to_postgres.py` to copy rows via SQLAlchemy.

6) Update your app settings and restart
- Ensure `requirements.txt` includes `psycopg2-binary` (done).
- Restart the app with `DATABASE_URL` set. The app will create tables if missing (via `db.create_all()` in `app.py`).

7) Updating file storage references after migration
- If you uploaded photos to Supabase Storage, update `Student.photo_path` values to the storage URLs (or public path). You can script this via a small Python script that maps local filenames to remote URLs.

8) Security
- Do not commit `DATABASE_URL` with credentials to source control.
- Use Supabase's API keys and RLS (Row Level Security) if you expose APIs.

Migration script
- See `scripts/migrate_sqlite_to_postgres.py` for a Python script that copies table data using SQLAlchemy.

Bulk upload helpers
- `scripts/upload_embeddings_to_supabase.py`: upserts all `data/embeddings/*.npy` into a Supabase table `face_embeddings` (jsonb embeddings).
- `scripts/upload_uploads_to_supabase.py`: uploads files under `uploads/` to a Supabase Storage bucket.

Create the `face_embeddings` table
- Run `scripts/create_face_embeddings_table.sql` in Supabase SQL editor, or execute this SQL manually:

```sql
create table if not exists face_embeddings (
  student_id int primary key,
  embedding jsonb
);
```

How to run the upload scripts (example)

PowerShell example (from project root):

```powershell
# Load vars from .env (optional)
pip install -r requirements.txt
$env:SUPABASE_URL = 'https://<project>.supabase.co'
$env:SUPABASE_KEY = '<anon-or-service-role-key>'
$env:SUPABASE_PHOTO_BUCKET = 'student_photos'
# Upload photos to storage
python .\scripts\upload_uploads_to_supabase.py
# Upload embeddings to table
python .\scripts\upload_embeddings_to_supabase.py
```

I can run these here for you if you provide `SUPABASE_URL` and `SUPABASE_KEY` (paste them or set them in the environment). If you prefer to run them yourself, the commands above will do it.
