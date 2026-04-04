# handlers/statistics.py
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from sqlalchemy import text, desc

from database import Session
from models import Student, Purchase, Event, EventParticipant
from config import ADMIN_IDS

router = Router()

BACK_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")]
])


async def send_profile(message, user_id: int, bot: Bot):
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            await message.answer("❌ Ты не зарегистрирован.")
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

        active_events = session.execute(text("""
            SELECT e.title, ep.event_balance
            FROM event_participants ep
            JOIN events e ON e.id = ep.event_id
            WHERE ep.student_id = :sid AND e.status = 'active'
        """), {"sid": student.id}).fetchall()

        student_id = student.id
        barcode = student.barcode
        qr_file_id = student.qr_file_id
        full_name = student.full_name
        balance = student.balance
        faculty = student.faculty

    caption = (
        f"👤 {full_name}\n"
        f"🔢 Баркод: {barcode}\n"
        f"🏛 Факультет: {faculty or '—'}\n\n"
        f"💰 Основной баланс: {balance}\n"
        f"🏆 Место в рейтинге: #{rank}\n"
    )
    if active_events:
        caption += "\n🎪 Баллы мероприятий:\n"
        for ev_title, ev_balance in active_events:
            caption += f"  • {ev_title}: {ev_balance} б.\n"

    caption += (
        f"\n📝 Заданий выполнено: {tasks_done}\n"
        f"🛍 Покупок: {purchases_count}\n"
        f"📥 Мероприятий посещено: {attended}"
    )

    # Кнопка обновить QR убрана — доступна только модератору через поиск студента
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Общий рейтинг",     callback_data="rating_all")],
        [InlineKeyboardButton(text="🏛 Рейтинг факультета", callback_data="rating_faculty")],
        [InlineKeyboardButton(text="🧾 Мои покупки",        callback_data="my_purchases")],
        [InlineKeyboardButton(text="⬅️ Назад",             callback_data="menu_back")],
    ])

    # Отправляем с QR
    if qr_file_id:
        try:
            await message.answer_photo(photo=qr_file_id, caption=caption, reply_markup=kb)
            return
        except Exception:
            with Session() as session:
                s = session.query(Student).get(student_id)
                if s:
                    s.qr_file_id = None
                    session.commit()

    try:
        from qr_generator import generate_qr_bytes
        qr_bytes = generate_qr_bytes(barcode)
        file = BufferedInputFile(qr_bytes, filename=f"qr_{barcode}.png")
        msg = await message.answer_photo(photo=file, caption=caption, reply_markup=kb)
        new_file_id = msg.photo[-1].file_id
        with Session() as session:
            s = session.query(Student).get(student_id)
            if s:
                s.qr_file_id = new_file_id
                session.commit()
    except Exception:
        await message.answer(caption, reply_markup=kb)


@router.callback_query(F.data == "my_profile")
async def show_my_profile(callback: CallbackQuery, bot: Bot):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_profile(callback.message, callback.from_user.id, bot)


@router.callback_query(F.data == "rating_all")
async def show_global_rating(callback: CallbackQuery):
    with Session() as session:
        top = session.query(Student).filter(Student.status == "active").order_by(desc(Student.balance)).limit(10).all()
    msg = "🏆 Топ‑10:\n\n" + "\n".join(f"{i}. {s.full_name} — {s.balance} б." for i, s in enumerate(top, 1)) if top else "Рейтинг пуст."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]])
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
    msg = f"🏛 Топ‑10 «{faculty}»:\n\n" + "\n".join(f"{i}. {s.full_name} — {s.balance} б." for i, s in enumerate(top, 1)) if top else f"Рейтинг «{faculty}» пуст."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, reply_markup=kb)


@router.callback_query(F.data == "my_purchases")
async def my_purchases(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await callback.answer("❌ Ты не зарегистрирован.", show_alert=True)
        purchases = session.query(Purchase).filter_by(student_id=student.id).all()
        items_info = []
        total_spent = 0
        for p in purchases:
            from models import Merchandise
            item = session.query(Merchandise).get(p.merch_id)
            name = item.name if item else "Удалённый товар"
            items_info.append(f"✅ {name} — {p.total_points} б. ({p.purchased_at.strftime('%d.%m.%Y')})")
            total_spent += p.total_points
    msg = f"🧾 *Мои покупки* ({len(items_info)} шт., {total_spent} б.):\n\n" + "\n".join(items_info) if items_info else "🧾 Покупок пока нет."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "stats")
async def show_admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")
    with Session() as session:
        total = session.query(Student).count()
        active = session.query(Student).filter_by(status="active").count()
        tasks = session.execute(text("SELECT COUNT(*) FROM task_verifications WHERE status = 'approved'")).scalar()
        purchases = session.execute(text("SELECT COUNT(*) FROM purchases")).scalar()
        active_events = session.query(Event).filter_by(status='active').count()
        total_parts = session.execute(text("SELECT COUNT(*) FROM event_participants")).scalar()
    msg = (
        f"📊 Статистика\n\n"
        f"👥 Студентов: {total} (активных: {active})\n"
        f"📝 Заданий выполнено: {tasks}\n"
        f"🛍 Покупок: {purchases}\n"
        f"🎪 Активных мероприятий: {active_events}\n"
        f"👥 Регистраций на мероприятия: {total_parts}\n"
    )
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, reply_markup=BACK_KB)
