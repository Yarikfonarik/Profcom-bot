from sqlalchemy import text
from database import engine

# подключаемся к базе и добавляем недостающий столбец
with engine.connect() as conn:
    try:
        conn.execute(text(
            "ALTER TABLE tasks ADD COLUMN verification_type VARCHAR(20) NOT NULL DEFAULT 'manual';"
        ))
        conn.commit()
        print("✅ Колонка verification_type успешно добавлена в таблицу tasks.")
    except Exception as e:
        print(f"⚠️ Ошибка: {e}")
