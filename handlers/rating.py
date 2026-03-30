# handlers/rating.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import desc

from database import Session
from models import Student

router = Router()

BACK_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⬅️ Назад", callback_data="rating")]
])


@router.callback_query(F.data == "rating")
async def show_rating_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "📊 Выбери рейтинг:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏆 Общий рейтинг",   callback_data="rating_all")],
            [InlineKeyboardButton(text="🏛 По факультету",   callback_data="rating_faculty")],
            [InlineKeyboardButton(text="⬅️ Назад",           callback_data="menu_back")],
        ])
    )


@router.callback_query(F.data == "rating_all")
async def show_global_rating(callback: CallbackQuery):
    with Session() as session:
        top10 = (
            session.query(Student)
            .filter(Student.status == "active")
            .order_by(desc(Student.balance))
            .limit(10)
            .all()
        )

    if not top10:
        msg = "🏆 Рейтинг пока пуст."
    else:
        lines = [f"{i}. {s.full_name} — {s.balance} баллов" for i, s in enumerate(top10, 1)]
        msg = "🏆 Топ‑10 студентов:\n\n" + "\n".join(lines)

    await callback.message.edit_text(msg, reply_markup=BACK_KB)


@router.callback_query(F.data == "rating_faculty")
async def show_faculty_rating(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        me = session.query(Student).filter_by(telegram_id=user_id).first()
        if not me:
            return await callback.answer("❌ Ты не зарегистрирован.", show_alert=True)

        top10 = (
            session.query(Student)
            .filter_by(faculty=me.faculty, status="active")
            .order_by(desc(Student.balance))
            .limit(10)
            .all()
        )

        faculty = me.faculty

    if not top10:
        msg = f"🏛 Рейтинг факультета «{faculty}» пока пуст."
    else:
        lines = [f"{i}. {s.full_name} — {s.balance} баллов" for i, s in enumerate(top10, 1)]
        msg = f"🏛 Топ‑10 факультета «{faculty}»:\n\n" + "\n".join(lines)

    await callback.message.edit_text(msg, reply_markup=BACK_KB)
