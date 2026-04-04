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
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';",
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS hidden BOOLEAN DEFAULT FALSE;",

    """CREATE TABLE IF NOT EXISTS event_participants (
        id SERIAL PRIMARY KEY,
        event_id INTEGER REFERENCES events(id),
        student_id INTEGER REFERENCES students(id),
        event_balance INTEGER DEFAULT 0,
        registered_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(event_id, student_id)
    );""",
    """CREATE TABLE IF NOT EXISTS lectures (
        id SERIAL PRIMARY KEY,
        event_id INTEGER REFERENCES events(id),
        title VARCHAR(255) NOT NULL,
        points INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
    );""",
    """CREATE TABLE IF NOT EXISTS lecture_scans (
        id SERIAL PRIMARY KEY,
        lecture_id INTEGER REFERENCES lectures(id),
        student_id INTEGER REFERENCES students(id),
        scanned_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(lecture_id, student_id)
    );""",
    """CREATE TABLE IF NOT EXISTS event_tasks (
        id SERIAL PRIMARY KEY,
        event_id INTEGER REFERENCES events(id),
        task_id INTEGER REFERENCES tasks(id),
        UNIQUE(event_id, task_id)
    );""",
    """CREATE TABLE IF NOT EXISTS event_merch (
        id SERIAL PRIMARY KEY,
        event_id INTEGER REFERENCES events(id),
        merch_id INTEGER REFERENCES merchandise(id),
        UNIQUE(event_id, merch_id)
    );""",
]

with engine.connect() as conn:
    for sql in migrations:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"✅ {sql.strip()[:65].replace(chr(10),' ')}")
        except Exception as e:
            print(f"⚠️  {e}")
