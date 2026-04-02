# handlers/statistics.py
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from sqlalchemy import text, desc

from database import Session
from models import Student, Purchase
from config import ADMIN_IDS

router = Router()

BACK_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")]
])


async def send_profile(target_message, user_id: int, bot: Bot, edit: bool = False):
    """Отправляет профиль с QR-кодом. Используется из нескольких мест."""
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            await target_message.answer("❌ Ты не зарегистрирован.")
            return

        rank = session.execute(
            text("SELECT rank FROM (SELECT id, RANK() OVER (ORDER BY balance DESC) as rank FROM students) r WHERE id = :id"),
            {"id": student.id}
        ).scalar()
        tasks_done = session.execute(
            text("SELECT COUNT(*) FROM task_verifications WHERE student_id = :id AND status = 'approved'"),
            {"id": student.id}
        ).scalar()
        purchases_count = session.execute(
            text("SELECT COUNT(*) FROM purchases WHERE student_id = :id"),
            {"id": student.id}
        ).scalar()
        attended = session.execute(
            text("SELECT COUNT(*) FROM attendance WHERE student_id = :id"),
            {"id": student.id}
        ).scalar()

        caption = (
            f"👤 {student.full_name}\n"
            f"🔢 Баркод: {student.barcode}\n"
            f"🏛 Факультет: {student.faculty or '—'}\n\n"
            f"💰 Баллов: {student.balance}\n"
            f"🏆 Место в рейтинге: #{rank}\n"
            f"📝 Заданий выполнено: {tasks_done}\n"
            f"🛍 Покупок: {purchases_count}\n"
            f"📥 Мероприятий посещено: {attended}"
        )

        student_id = student.id
        barcode = student.barcode
        qr_file_id = student.qr_file_id

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Общий рейтинг",     callback_data="rating_all")],
        [InlineKeyboardButton(text="🏛 Рейтинг факультета", callback_data="rating_faculty")],
        [InlineKeyboardButton(text="🧾 Мои покупки",        callback_data="my_purchases")],
        [InlineKeyboardButton(text="🔄 Обновить QR",        callback_data="refresh_qr")],
        [InlineKeyboardButton(text="⬅️ Назад",             callback_data="menu_back")],
    ])

    # Пробуем отправить с кэшированным QR
    if qr_file_id:
        try:
            await target_message.answer_photo(photo=qr_file_id, caption=caption, reply_markup=kb)
            return
        except Exception:
            # file_id устарел — сбрасываем
            with Session() as session:
                s = session.query(Student).get(student_id)
                if s:
                    s.qr_file_id = None
                    session.commit()

    # Генерируем новый QR
    try:
        from qr_generator import generate_qr_bytes
        qr_bytes = generate_qr_bytes(barcode)
        file = BufferedInputFile(qr_bytes, filename=f"qr_{barcode}.png")
        msg = await target_message.answer_photo(photo=file, caption=caption, reply_markup=kb)

        # Кэшируем file_id
        new_file_id = msg.photo[-1].file_id
        with Session() as session:
            s = session.query(Student).get(student_id)
            if s:
                s.qr_file_id = new_file_id
                session.commit()
    except Exception as e:
        # QR не удалось — показываем без фото
        await target_message.answer(caption, reply_markup=kb)


@router.callback_query(F.data == "my_profile")
async def show_my_profile(callback: CallbackQuery, bot: Bot):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_profile(callback.message, callback.from_user.id, bot)


@router.callback_query(F.data == "refresh_qr")
async def refresh_qr(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if student:
            student.qr_file_id = None
            session.commit()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("🔄 Обновляю QR...")
    await send_profile(callback.message, user_id, bot)


@router.callback_query(F.data == "rating_all")
async def show_global_rating(callback: CallbackQuery):
    with Session() as session:
        top = session.query(Student).filter(Student.status == "active").order_by(desc(Student.balance)).limit(10).all()

    msg = "🏆 Топ‑10 студентов:\n\n" + "\n".join(
        f"{i}. {s.full_name} — {s.balance} б." for i, s in enumerate(top, 1)
    ) if top else "🏆 Рейтинг пока пуст."

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

    msg = f"🏛 Топ‑10 «{faculty}»:\n\n" + "\n".join(
        f"{i}. {s.full_name} — {s.balance} б." for i, s in enumerate(top, 1)
    ) if top else f"🏛 Рейтинг «{faculty}» пуст."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]
    ])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, reply_markup=kb)


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
        top_faculties = session.execute(text(
            "SELECT faculty, SUM(balance) AS total FROM students WHERE faculty IS NOT NULL GROUP BY faculty ORDER BY total DESC LIMIT 3"
        )).fetchall()

    msg = (
        f"📊 Статистика системы\n\n"
        f"👥 Всего: {total} | Активных: {active}\n"
        f"🧑‍💼 Адм. и модераторов: {staff}\n"
        f"📝 Заданий выполнено: {tasks}\n"
        f"🛍 Покупок: {purchases}\n"
        f"📥 Посещений: {events}\n"
    )
    if top_faculties:
        msg += "\n🏛 Топ факультетов:\n"
        for idx, (name, tp) in enumerate(top_faculties, 1):
            msg += f"{idx}. {name} — {tp} б.\n"

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, reply_markup=BACK_KB)
