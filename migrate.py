# migrate.py
from sqlalchemy import text
from database import engine

with engine.connect() as conn:
    migrations = [
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS deadline TIMESTAMP;",
        "ALTER TABLE merchandise ADD COLUMN IF NOT EXISTS photo_file_id VARCHAR(255);",
    ]
    for sql in migrations:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"✅ {sql}")
        except Exception as e:
            print(f"⚠️ {e}")
