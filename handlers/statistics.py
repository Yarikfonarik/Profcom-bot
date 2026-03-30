# handlers/statistics.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import text

from database import Session
from models import Student
from config import ADMIN_IDS

router = Router()

BACK_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")]
])


# ── Статистика системы (только для админов) ─────────────────────────────────
@router.callback_query(F.data == "stats")
async def show_admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")

    with Session() as session:
        total = session.query(Student).count()
        active = session.query(Student).filter_by(status="active").count()
        staff = session.query(Student).filter(
            Student.role.in_(["admin", "moderator"])
        ).count()
        tasks = session.execute(
            text("SELECT COUNT(*) FROM task_verifications WHERE status = 'approved'")
        ).scalar()
        purchases = session.execute(
            text("SELECT COUNT(*) FROM purchases")
        ).scalar()
        events = session.execute(
            text("SELECT COUNT(*) FROM attendance")
        ).scalar()
        top_faculties = session.execute(text("""
            SELECT faculty, SUM(balance) AS total
            FROM students
            WHERE faculty IS NOT NULL
            GROUP BY faculty
            ORDER BY total DESC
            LIMIT 3
        """)).fetchall()

    msg = (
        f"📊 Статистика системы\n\n"
        f"👥 Всего студентов: {total}\n"
        f"🧑‍🎓 Активных: {active}\n"
        f"🧑‍💼 Админов и модераторов: {staff}\n"
        f"📝 Заданий выполнено: {tasks}\n"
        f"🛍 Покупок совершено: {purchases}\n"
        f"📥 Посещений мероприятий: {events}\n"
    )
    if top_faculties:
        msg += "\n🏛 Топ факультетов:\n"
        for idx, (name, total_pts) in enumerate(top_faculties, 1):
            msg += f"{idx}. {name} — {total_pts} баллов\n"

    await callback.message.edit_text(msg, reply_markup=BACK_KB)


# ── Моя личная статистика ───────────────────────────────────────────────────
@router.callback_query(F.data == "my_stats")
async def show_my_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await callback.answer("❌ Ты не зарегистрирован.", show_alert=True)

        rank = session.execute(
            text("SELECT RANK() OVER (ORDER BY balance DESC) FROM students WHERE id = :id"),
            {"id": student.id}
        ).scalar()
        tasks_done = session.execute(
            text("SELECT COUNT(*) FROM task_verifications WHERE student_id = :id AND status = 'approved'"),
            {"id": student.id}
        ).scalar()
        purchases = session.execute(
            text("SELECT COUNT(*) FROM purchases WHERE student_id = :id"),
            {"id": student.id}
        ).scalar()
        attended = session.execute(
            text("SELECT COUNT(*) FROM attendance WHERE student_id = :id"),
            {"id": student.id}
        ).scalar()

        name = student.full_name
        balance = student.balance

    msg = (
        f"📈 Твоя статистика\n\n"
        f"👤 {name}\n"
        f"💰 Баллов: {balance}\n"
        f"🏆 Место в рейтинге: #{rank}\n\n"
        f"📝 Заданий выполнено: {tasks_done}\n"
        f"🛍 Покупок: {purchases}\n"
        f"📥 Мероприятий посещено: {attended}"
    )
    await callback.message.edit_text(msg, reply_markup=BACK_KB)
