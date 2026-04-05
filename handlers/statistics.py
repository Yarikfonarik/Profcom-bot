# handlers/statistics.py
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from sqlalchemy import text, desc

from database import Session
from models import Student, Purchase, Event, EventParticipant, Task, TaskVerification, Merchandise, LectureScan
from config import ADMIN_IDS

router = Router()
BACK_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")]])


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

        # Выполненные задания
        done_tasks = session.execute(text("""
            SELECT t.title FROM task_verifications tv
            JOIN tasks t ON t.id = tv.task_id
            WHERE tv.student_id = :id AND tv.status = 'approved'
            ORDER BY tv.submitted_at DESC LIMIT 5
        """), {"id": student.id}).fetchall()

        # Посещённые мероприятия
        visited_events = session.execute(text("""
            SELECT e.title, ep.event_balance FROM event_participants ep
            JOIN events e ON e.id = ep.event_id
            WHERE ep.student_id = :id
            ORDER BY ep.registered_at DESC LIMIT 5
        """), {"id": student.id}).fetchall()

        # Активные мероприятия с балансами
        active_events = session.execute(text("""
            SELECT e.title, ep.event_balance FROM event_participants ep
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

    caption += f"\n📝 Заданий выполнено: {tasks_done}\n"
    if done_tasks:
        caption += "".join(f"  ✅ {r[0]}\n" for r in done_tasks)

    caption += f"\n🛍 Покупок: {purchases_count}\n"
    caption += f"\n📥 Посещённые мероприятия:\n"
    if visited_events:
        for ev_title, ev_bal in visited_events:
            caption += f"  • {ev_title}\n"
    else:
        caption += "  —\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Рейтинг",          callback_data="rating_all")],
        [InlineKeyboardButton(text="🧾 Мои покупки",       callback_data="my_purchases")],
        [InlineKeyboardButton(text="⬅️ Назад",            callback_data="menu_back")],
    ])

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
    try: await callback.message.delete()
    except Exception: pass
    await send_profile(callback.message, callback.from_user.id, bot)


# ── Единый рейтинг (общий + факультет) ───────────────────────────────────────
@router.callback_query(F.data == "rating_all")
async def show_rating(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        top_global = session.query(Student).filter(Student.status == "active").order_by(desc(Student.balance)).limit(10).all()
        me = session.query(Student).filter_by(telegram_id=user_id).first()
        top_faculty = []
        faculty = None
        if me and me.faculty:
            faculty = me.faculty
            top_faculty = session.query(Student).filter_by(faculty=faculty, status="active").order_by(desc(Student.balance)).limit(10).all()

    msg = "🏆 *Общий рейтинг* (топ‑10):\n\n"
    msg += "\n".join(f"{i}. {s.full_name} — {s.balance} б." for i, s in enumerate(top_global, 1)) if top_global else "Пусто"

    if faculty and top_faculty:
        msg += f"\n\n🏛 *Рейтинг «{faculty}»* (топ‑10):\n\n"
        msg += "\n".join(f"{i}. {s.full_name} — {s.balance} б." for i, s in enumerate(top_faculty, 1))

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "my_purchases")
async def my_purchases(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await callback.answer("❌ Не зарегистрирован.", show_alert=True)
        purchases = session.query(Purchase).filter_by(student_id=student.id).all()
        items_info = []
        total_spent = 0
        for p in purchases:
            item = session.query(Merchandise).get(p.merch_id)
            name = item.name if item else "Удалённый товар"
            items_info.append(f"✅ {name} — {p.total_points} б. ({p.purchased_at.strftime('%d.%m.%Y')})")
            total_spent += p.total_points

    msg = f"🧾 *Мои покупки* ({len(items_info)} шт., {total_spent} б.):\n\n" + "\n".join(items_info) if items_info else "🧾 Покупок пока нет."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ── Статистика заданий (модератор) ───────────────────────────────────────────
@router.callback_query(F.data == "task_stats_menu")
async def task_stats_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)

    with Session() as session:
        total_done = session.execute(text("SELECT COUNT(*) FROM task_verifications WHERE status = 'approved'")).scalar()
        tasks = session.query(Task).filter_by(is_deleted=False).all()

    buttons = []
    for t in tasks:
        buttons.append([InlineKeyboardButton(text=f"📝 {t.title}", callback_data=f"task_stat_{t.id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])

    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        f"📝 *Статистика заданий*\n\nВсего выполнено: {total_done}\n\nВыбери задание для деталей:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("task_stat_"))
async def task_stat_detail(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[2])
    with Session() as session:
        task = session.query(Task).get(task_id)
        approved = session.execute(
            text("SELECT COUNT(*) FROM task_verifications WHERE task_id = :id AND status = 'approved'"),
            {"id": task_id}
        ).scalar()
        pending = session.execute(
            text("SELECT COUNT(*) FROM task_verifications WHERE task_id = :id AND status = 'pending'"),
            {"id": task_id}
        ).scalar()
        rejected = session.execute(
            text("SELECT COUNT(*) FROM task_verifications WHERE task_id = :id AND status = 'rejected'"),
            {"id": task_id}
        ).scalar()
        # Последние выполнившие
        recent = session.execute(text("""
            SELECT s.full_name, tv.submitted_at FROM task_verifications tv
            JOIN students s ON s.id = tv.student_id
            WHERE tv.task_id = :id AND tv.status = 'approved'
            ORDER BY tv.submitted_at DESC LIMIT 5
        """), {"id": task_id}).fetchall()

    msg = (
        f"📌 *{task.title}*\n\n"
        f"✅ Выполнили: {approved}\n"
        f"⏳ На проверке: {pending}\n"
        f"❌ Отклонено: {rejected}\n"
    )
    if recent:
        msg += "\n*Последние выполнившие:*\n"
        for name, dt in recent:
            msg += f"• {name} — {dt.strftime('%d.%m %H:%M')}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="task_stats_menu")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ── Статистика магазина (модератор) ──────────────────────────────────────────
@router.callback_query(F.data == "shop_stats_menu")
async def shop_stats_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав", show_alert=True)

    with Session() as session:
        total_purchases = session.execute(text("SELECT COUNT(*) FROM purchases")).scalar()
        total_spent = session.execute(text("SELECT COALESCE(SUM(total_points),0) FROM purchases")).scalar()
        items = session.query(Merchandise).filter_by(is_deleted=False).all()

    buttons = []
    for item in items:
        buttons.append([InlineKeyboardButton(text=f"🛍 {item.name}", callback_data=f"shop_stat_{item.id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])

    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        f"🛍 *Статистика магазина*\n\nВсего покупок: {total_purchases}\nПотрачено баллов: {total_spent}\n\nВыбери товар для деталей:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("shop_stat_"))
async def shop_stat_detail(callback: CallbackQuery):
    item_id = int(callback.data.split("_")[2])
    with Session() as session:
        item = session.query(Merchandise).get(item_id)
        bought_count = session.execute(
            text("SELECT COUNT(*) FROM purchases WHERE merch_id = :id"),
            {"id": item_id}
        ).scalar()
        total_spent = session.execute(
            text("SELECT COALESCE(SUM(total_points),0) FROM purchases WHERE merch_id = :id"),
            {"id": item_id}
        ).scalar()
        recent = session.execute(text("""
            SELECT s.full_name, p.purchased_at FROM purchases p
            JOIN students s ON s.id = p.student_id
            WHERE p.merch_id = :id
            ORDER BY p.purchased_at DESC LIMIT 5
        """), {"id": item_id}).fetchall()

    msg = (
        f"🛍 *{item.name}*\n\n"
        f"🛒 Куплено раз: {bought_count}\n"
        f"💰 Потрачено баллов: {total_spent}\n"
        f"📦 Осталось: {item.stock}\n"
    )
    if recent:
        msg += "\n*Последние покупки:*\n"
        for name, dt in recent:
            msg += f"• {name} — {dt.strftime('%d.%m %H:%M')}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="shop_stats_menu")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "stats")
async def show_admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")
    with Session() as session:
        total = session.query(Student).count()
        active_s = session.query(Student).filter_by(status="active").count()
        tasks = session.execute(text("SELECT COUNT(*) FROM task_verifications WHERE status = 'approved'")).scalar()
        purchases = session.execute(text("SELECT COUNT(*) FROM purchases")).scalar()
        active_ev = session.query(Event).filter_by(status='active').count()
        total_parts = session.execute(text("SELECT COUNT(*) FROM event_participants")).scalar()

    msg = (
        f"📊 *Статистика системы*\n\n"
        f"👥 Студентов: {total} (активных: {active_s})\n"
        f"📝 Заданий выполнено: {tasks}\n"
        f"🛍 Покупок: {purchases}\n"
        f"🎪 Активных мероприятий: {active_ev}\n"
        f"👥 Регистраций: {total_parts}\n"
    )
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=BACK_KB)
