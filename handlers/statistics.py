# handlers/statistics.py — Профиль + Рейтинг объединены
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import text, desc

from database import Session
from models import Student
from config import ADMIN_IDS

router = Router()

BACK_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")]
])


# ── Профиль (объединён с рейтингом) ─────────────────────────────────────────
@router.callback_query(F.data == "my_profile")
async def show_my_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await callback.answer("❌ Ты не зарегистрирован.", show_alert=True)

        rank = session.execute(
            text("""
                SELECT rank FROM (
                    SELECT id, RANK() OVER (ORDER BY balance DESC) as rank FROM students
                ) r WHERE id = :id
            """),
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

        status = "✅ Активен" if student.status == "active" else "⛔ Заблокирован"
        msg = (
            f"👤 *{student.full_name}*\n\n"
            f"🔢 Баркод: `{student.barcode}`\n"
            f"🏛 Факультет: {student.faculty or '—'}\n"
            f"💰 Баллов: *{student.balance}*\n"
            f"🏆 Место в рейтинге: #{rank}\n"
            f"📊 Статус: {status}\n\n"
            f"📝 Заданий выполнено: {tasks_done}\n"
            f"🛍 Покупок: {purchases}\n"
            f"📥 Мероприятий посещено: {attended}"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Общий рейтинг",      callback_data="rating_all")],
        [InlineKeyboardButton(text="🏛 Рейтинг факультета",  callback_data="rating_faculty")],
        [InlineKeyboardButton(text="⬅️ Назад",              callback_data="menu_back")],
    ])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ── Рейтинги ─────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "rating_all")
async def show_global_rating(callback: CallbackQuery):
    with Session() as session:
        top = session.query(Student).filter(Student.status == "active").order_by(desc(Student.balance)).limit(10).all()

    if not top:
        msg = "🏆 Рейтинг пока пуст."
    else:
        lines = [f"{i}. {s.full_name} — {s.balance} б." for i, s in enumerate(top, 1)]
        msg = "🏆 Топ‑10 студентов:\n\n" + "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]
    ])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, reply_markup=kb)


@router.callback_query(F.data == "rating_faculty")
async def show_faculty_rating(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        me = session.query(Student).filter_by(telegram_id=user_id).first()
        if not me:
            return await callback.answer("❌ Ты не зарегистрирован.", show_alert=True)
        top = session.query(Student).filter_by(faculty=me.faculty, status="active").order_by(desc(Student.balance)).limit(10).all()
        faculty = me.faculty

    if not top:
        msg = f"🏛 Рейтинг факультета «{faculty}» пуст."
    else:
        lines = [f"{i}. {s.full_name} — {s.balance} б." for i, s in enumerate(top, 1)]
        msg = f"🏛 Топ‑10 «{faculty}»:\n\n" + "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]
    ])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, reply_markup=kb)


# ── Статистика системы (только для админов) ──────────────────────────────────
@router.callback_query(F.data == "stats")
async def show_admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")

    with Session() as session:
        total = session.query(Student).count()
        active = session.query(Student).filter_by(status="active").count()
        staff = session.query(Student).filter(Student.role.in_(["admin", "moderator"])).count()
        tasks = session.execute(text("SELECT COUNT(*) FROM task_verifications WHERE status = 'approved'")).scalar()
        purchases = session.execute(text("SELECT COUNT(*) FROM purchases")).scalar()
        events = session.execute(text("SELECT COUNT(*) FROM attendance")).scalar()
        top_faculties = session.execute(text("""
            SELECT faculty, SUM(balance) AS total FROM students
            WHERE faculty IS NOT NULL GROUP BY faculty ORDER BY total DESC LIMIT 3
        """)).fetchall()

    msg = (
        f"📊 Статистика системы\n\n"
        f"👥 Всего: {total} | Активных: {active}\n"
        f"🧑‍💼 Админов и модераторов: {staff}\n"
        f"📝 Заданий выполнено: {tasks}\n"
        f"🛍 Покупок: {purchases}\n"
        f"📥 Посещений: {events}\n"
    )
    if top_faculties:
        msg += "\n🏛 Топ факультетов:\n"
        for idx, (name, total_pts) in enumerate(top_faculties, 1):
            msg += f"{idx}. {name} — {total_pts} б.\n"

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, reply_markup=BACK_KB)
