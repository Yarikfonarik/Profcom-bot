# handlers/statistics.py
import io
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


async def _get_or_create_qr(student, bot: Bot) -> str | None:
    """Возвращает file_id QR кода. Генерирует и кэширует если нет."""
    if student.qr_file_id:
        return student.qr_file_id

    if not student.barcode:
        return None

    try:
        from qr_generator import generate_qr_bytes
        qr_bytes = generate_qr_bytes(student.barcode)

        # Отправляем боту чтобы получить file_id (в служебный чат к себе)
        # Используем send_photo к самому пользователю и забираем file_id
        file = BufferedInputFile(qr_bytes, filename=f"qr_{student.barcode}.png")
        # Отправляем фото и сразу удаляем — только чтобы получить file_id
        msg = await bot.send_photo(
            chat_id=student.telegram_id,
            photo=file,
            caption="",
        )
        file_id = msg.photo[-1].file_id

        # Удаляем сообщение
        try:
            await bot.delete_message(student.telegram_id, msg.message_id)
        except Exception:
            pass

        # Сохраняем file_id
        with Session() as session:
            s = session.query(Student).get(student.id)
            if s:
                s.qr_file_id = file_id
                session.commit()

        return file_id

    except Exception as e:
        print(f"QR generation error: {e}")
        return None


@router.callback_query(F.data == "my_profile")
async def show_my_profile(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await callback.answer("❌ Ты не зарегистрирован.", show_alert=True)

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

        status = "✅ Активен" if student.status == "active" else "⛔ Заблокирован"
        msg = (
            f"👤 *{student.full_name}*\n\n"
            f"🔢 Баркод: `{student.barcode}`\n"
            f"🏛 Факультет: {student.faculty or '—'}\n"
            f"💰 Баллов: *{student.balance}*\n"
            f"🏆 Место в рейтинге: #{rank}\n"
            f"📊 Статус: {status}\n\n"
            f"📝 Заданий выполнено: {tasks_done}\n"
            f"🛍 Покупок: {purchases_count}\n"
            f"📥 Мероприятий посещено: {attended}"
        )

        # Собираем данные для QR пока сессия открыта
        student_id = student.id
        barcode = student.barcode
        qr_file_id = student.qr_file_id
        full_name = student.full_name
        balance = student.balance

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Общий рейтинг",      callback_data="rating_all")],
        [InlineKeyboardButton(text="🏛 Рейтинг факультета",  callback_data="rating_faculty")],
        [InlineKeyboardButton(text="🧾 Мои покупки",         callback_data="my_purchases")],
        [InlineKeyboardButton(text="📷 Мой QR-код",          callback_data="my_qr")],
        [InlineKeyboardButton(text="⬅️ Назад",              callback_data="menu_back")],
    ])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "my_qr")
async def show_my_qr(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await callback.answer("❌ Ты не зарегистрирован.", show_alert=True)
        if not student.barcode:
            return await callback.answer("❌ У тебя нет баркода.", show_alert=True)

        student_id = student.id
        barcode = student.barcode
        qr_file_id = student.qr_file_id
        full_name = student.full_name
        balance = student.balance

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить QR", callback_data="refresh_qr")],
        [InlineKeyboardButton(text="⬅️ Назад",       callback_data="my_profile")],
    ])

    caption = (
        f"📷 *QR-код*\n\n"
        f"👤 {full_name} (`{barcode}`)\n\n"
        f"💰 Всего баллов: {balance}"
    )

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer("⏳ Генерирую QR-код...")

    # Получаем или создаём QR
    if qr_file_id:
        try:
            await callback.message.answer_photo(photo=qr_file_id, caption=caption, parse_mode="Markdown", reply_markup=kb)
            return
        except Exception:
            # file_id устарел — сбросим и сгенерируем заново
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
        msg = await callback.message.answer_photo(photo=file, caption=caption, parse_mode="Markdown", reply_markup=kb)

        # Кэшируем file_id
        new_file_id = msg.photo[-1].file_id
        with Session() as session:
            s = session.query(Student).get(student_id)
            if s:
                s.qr_file_id = new_file_id
                session.commit()

    except Exception as e:
        await callback.message.answer(f"❌ Не удалось создать QR: {e}", reply_markup=kb)


@router.callback_query(F.data == "refresh_qr")
async def refresh_qr(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id

    # Сбрасываем кэш
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if student:
            student.qr_file_id = None
            session.commit()

    await callback.answer("🔄 Обновляю QR...")
    # Переиспользуем show_my_qr
    callback.data = "my_qr"
    await show_my_qr(callback, bot)


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
