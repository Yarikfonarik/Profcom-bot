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
    "ALTER TABLE task_verifications ADD COLUMN IF NOT EXISTS proof_type VARCHAR(20) DEFAULT 'photo';",
    # Events
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';",
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS hidden BOOLEAN DEFAULT FALSE;",
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS description TEXT;",
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS image_file_id VARCHAR(255);",
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS event_date VARCHAR(100);",
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS how_to_join TEXT;",
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS has_tasks BOOLEAN DEFAULT TRUE;",
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS has_lectures BOOLEAN DEFAULT TRUE;",
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS has_shop BOOLEAN DEFAULT TRUE;",
    # Event merch custom fields
    "ALTER TABLE event_merch ADD COLUMN IF NOT EXISTS custom_stock INTEGER;",
    "ALTER TABLE event_merch ADD COLUMN IF NOT EXISTS custom_price INTEGER;",
    # New tables
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
        custom_stock INTEGER,
        custom_price INTEGER,
        UNIQUE(event_id, merch_id)
    );""",
    """CREATE TABLE IF NOT EXISTS support_tickets (
        id SERIAL PRIMARY KEY,
        student_telegram_id INTEGER NOT NULL,
        moderator_telegram_id INTEGER,
        status VARCHAR(20) DEFAULT 'open',
        created_at TIMESTAMP DEFAULT NOW()
    );""",
    """CREATE TABLE IF NOT EXISTS support_messages (
        id SERIAL PRIMARY KEY,
        ticket_id INTEGER REFERENCES support_tickets(id),
        sender_id INTEGER NOT NULL,
        text TEXT,
        file_id VARCHAR(255),
        file_type VARCHAR(20),
        sent_at TIMESTAMP DEFAULT NOW()
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

# Дополнительные поля для SupportTicket
extra_migrations = [
    "ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS event_id INTEGER REFERENCES events(id);",
]

with engine.connect() as conn2:
    for sql in extra_migrations:
        try:
            conn2.execute(text(sql))
            conn2.commit()
            print(f"✅ {sql[:65]}")
        except Exception as e:
            print(f"⚠️  {e}")
