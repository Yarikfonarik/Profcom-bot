# migrate.py
from sqlalchemy import text
from database import engine

migrations = [
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS deadline TIMESTAMP;",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE merchandise ADD COLUMN IF NOT EXISTS photo_file_id VARCHAR(255);",
    "ALTER TABLE merchandise ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;",
]

with engine.connect() as conn:
    for sql in migrations:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"✅ {sql[:60]}")
        except Exception as e:
            print(f"⚠️ {e}")
