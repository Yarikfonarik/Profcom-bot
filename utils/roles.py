# utils/roles.py
from sqlalchemy import text
from database import Session


def is_admin_or_moderator(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором или модератором."""
    with Session() as session:
        result = session.execute(
            text("SELECT role FROM students WHERE telegram_id = :uid"),
            {"uid": user_id}
        )
        role = result.scalar()
    return role in ("admin", "moderator")
