# migrate.py
from sqlalchemy import text
from database import engine

migrations = [
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS deadline TIMESTAMP;",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS show_deadline BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE merchandise ADD COLUMN IF NOT EXISTS photo_file_id VARCHAR(255);",
    "ALTER TABLE merchandise ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE students ADD COLUMN IF NOT EXISTS qr_file_id VARCHAR(255);",
]

with engine.connect() as conn:
    for sql in migrations:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"✅ {sql[:70]}")
        except Exception as e:
            print(f"⚠️ {e}")
