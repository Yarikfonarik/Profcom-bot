# handlers/statistics.py
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from sqlalchemy import text, desc

from database import Session
from models import Student, Purchase, Event, EventParticipant, Task, TaskVerification, Merchandise
from config import ADMIN_IDS

router = Router()
BACK_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")]])


def _profile_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🏆 Рейтинг",             callback_data="rating_all")],
        [InlineKeyboardButton(text="📝 Мои задания",          callback_data="my_tasks_done")],
        [InlineKeyboardButton(text="🛍 Мои покупки",          callback_data="my_purchases")],
        [InlineKeyboardButton(text="📥 Мои мероприятия",      callback_data="my_events_list")],
        [InlineKeyboardButton(text="📷 Мой QR-код",           callback_data="my_qr")],
        [InlineKeyboardButton(text="⬅️ Назад",               callback_data="menu_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _build_profile_caption(student_id: int) -> str:
    with Session() as session:
        s = session.query(Student).get(student_id)
        rank = session.execute(
            text("SELECT rank FROM (SELECT id, RANK() OVER (ORDER BY balance DESC) as rank FROM students) r WHERE id = :id"),
            {"id": student_id}
        ).scalar()
        tasks_done = session.execute(
            text("SELECT COUNT(*) FROM task_verifications WHERE student_id = :id AND status = 'approved'"),
            {"id": student_id}
        ).scalar()
        purchases_count = session.execute(
            text("SELECT COUNT(*) FROM purchases WHERE student_id = :id"),
            {"id": student_id}
        ).scalar()
        events_count = session.execute(
            text("SELECT COUNT(*) FROM event_participants WHERE student_id = :id"),
            {"id": student_id}
        ).scalar()
        active_events = session.execute(text("""
            SELECT e.title, ep.event_balance FROM event_participants ep
            JOIN events e ON e.id = ep.event_id
            WHERE ep.student_id = :sid AND e.status = 'active'
        """), {"sid": student_id}).fetchall()

    caption = (
        f"👤 {s.full_name}\n"
        f"🔢 Баркод: {s.barcode}\n"
        f"🏛 Факультет: {s.faculty or '—'}\n\n"
        f"💰 Основной баланс: {s.balance}\n"
        f"🏆 Место в рейтинге: #{rank}\n\n"
        f"📝 Заданий выполнено: {tasks_done}\n"
        f"🛍 Покупок: {purchases_count}\n"
        f"📥 Мероприятий: {events_count}\n"
    )
    if active_events:
        caption += "\n🎪 Активные мероприятия:\n"
        for ev_title, ev_bal in active_events:
            caption += f"  • {ev_title}: {ev_bal} б.\n"
    return caption


async def show_my_profile_msg(message: Message):
    """Показать профиль как обычное сообщение (из команды /profile)."""
    user_id = message.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await message.answer("❌ Ты не зарегистрирован.")
        student_id = student.id
        qr_file_id = student.qr_file_id
        barcode = student.barcode

    caption = await _build_profile_caption(student_id)
    kb = _profile_kb(user_id in ADMIN_IDS)

    if qr_file_id:
        try:
            await message.answer_photo(photo=qr_file_id, caption=caption, reply_markup=kb)
            return
        except Exception:
            pass

    # Без QR — просто текст (быстро)
    await message.answer(caption, reply_markup=kb)


@router.callback_query(F.data == "my_profile")
async def show_my_profile(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    try: await callback.message.delete()
    except Exception: pass

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await callback.message.answer("❌ Ты не зарегистрирован.")
        student_id = student.id
        qr_file_id = student.qr_file_id
        barcode = student.barcode

    caption = await _build_profile_caption(student_id)
    kb = _profile_kb(user_id in ADMIN_IDS)

    # Сначала отправляем без QR — быстро
    msg = await callback.message.answer(caption, reply_markup=kb)

    # Если есть кэшированный QR — обновляем сообщение (редко нужен перегруз)
    if qr_file_id:
        try:
            await msg.delete()
            await callback.message.answer_photo(photo=qr_file_id, caption=caption, reply_markup=kb)
        except Exception:
            pass  # оставляем текстовое


@router.callback_query(F.data == "my_qr")
async def show_my_qr(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            return await callback.answer("❌ Не зарегистрирован", show_alert=True)
        student_id = student.id
        barcode = student.barcode
        qr_file_id = student.qr_file_id

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Пересоздать QR", callback_data="refresh_qr")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")],
    ])

    await callback.answer("⏳ Загружаю QR...")
    try: await callback.message.delete()
    except Exception: pass

    if qr_file_id:
        try:
            await callback.message.answer_photo(photo=qr_file_id, caption=f"📷 QR-код\n`{barcode}`", parse_mode="Markdown", reply_markup=kb)
            return
        except Exception:
            with Session() as session:
                s = session.query(Student).get(student_id)
                if s: s.qr_file_id = None; session.commit()

    try:
        from qr_generator import generate_qr_bytes
        qr_bytes = generate_qr_bytes(barcode)
        file = BufferedInputFile(qr_bytes, filename=f"qr_{barcode}.png")
        msg = await callback.message.answer_photo(photo=file, caption=f"📷 QR-код\n`{barcode}`", parse_mode="Markdown", reply_markup=kb)
        with Session() as session:
            s = session.query(Student).get(student_id)
            if s: s.qr_file_id = msg.photo[-1].file_id; session.commit()
    except Exception as e:
        await callback.message.answer(f"❌ Не удалось сгенерировать QR: {e}", reply_markup=kb)


@router.callback_query(F.data == "refresh_qr")
async def refresh_qr(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if student: student.qr_file_id = None; session.commit()
    try: await callback.message.delete()
    except Exception: pass
    callback.data = "my_qr"
    await show_my_qr(callback, bot)


# ── Детали профиля ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_tasks_done")
async def my_tasks_done(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student: return await callback.answer("❌ Не зарегистрирован", show_alert=True)
        rows = session.execute(text("""
            SELECT t.title, t.points, tv.submitted_at
            FROM task_verifications tv JOIN tasks t ON t.id = tv.task_id
            WHERE tv.student_id = :id AND tv.status = 'approved'
            ORDER BY tv.submitted_at DESC
        """), {"id": student.id}).fetchall()

    if not rows:
        msg = "📝 Ты ещё не выполнил ни одного задания."
    else:
        lines = [f"{i}. ✅ {r[0]} — {r[1]} б. ({r[2].strftime('%d.%m')})" for i, r in enumerate(rows, 1)]
        msg = f"📝 *Выполненные задания* ({len(rows)}):\n\n" + "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "my_events_list")
async def my_events_list(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student: return await callback.answer("❌ Не зарегистрирован", show_alert=True)
        rows = session.execute(text("""
            SELECT e.title, e.status, ep.event_balance, ep.registered_at
            FROM event_participants ep JOIN events e ON e.id = ep.event_id
            WHERE ep.student_id = :id ORDER BY ep.registered_at DESC
        """), {"id": student.id}).fetchall()

    if not rows:
        msg = "📥 Ты ещё не участвовал ни в одном мероприятии."
    else:
        lines = []
        for r in rows:
            icon = "🟢" if r[1] == "active" else "🔴"
            bal = f" | {r[2]} б." if r[1] == "active" else ""
            lines.append(f"{icon} {r[0]}{bal}")
        msg = f"📥 *Мои мероприятия* ({len(rows)}):\n\n" + "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "my_purchases")
async def my_purchases(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student: return await callback.answer("❌ Не зарегистрирован", show_alert=True)
        purchases = session.query(Purchase).filter_by(student_id=student.id).all()
        items_info, total_spent = [], 0
        for p in purchases:
            item = session.query(Merchandise).get(p.merch_id)
            name = item.name if item else "Удалённый товар"
            items_info.append(f"✅ {name} — {p.total_points} б. ({p.purchased_at.strftime('%d.%m.%Y')})")
            total_spent += p.total_points

    msg = f"🧾 *Покупки* ({len(items_info)} шт., {total_spent} б.):\n\n" + "\n".join(items_info) if items_info else "🧾 Покупок пока нет."
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ── Рейтинг ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "rating_all")
async def show_rating(callback: CallbackQuery):
    user_id = callback.from_user.id
    with Session() as session:
        top = session.query(Student).filter(Student.status == "active").order_by(desc(Student.balance)).limit(10).all()
        me = session.query(Student).filter_by(telegram_id=user_id).first()
        top_fac, faculty = [], None
        if me and me.faculty:
            faculty = me.faculty
            top_fac = session.query(Student).filter_by(faculty=faculty, status="active").order_by(desc(Student.balance)).limit(10).all()

    msg = "🏆 *Общий рейтинг* (топ‑10):\n\n"
    msg += "\n".join(f"{i}. {s.full_name} — {s.balance} б." for i, s in enumerate(top, 1)) if top else "Пусто"
    if faculty and top_fac:
        msg += f"\n\n🏛 *Рейтинг «{faculty}»*:\n\n"
        msg += "\n".join(f"{i}. {s.full_name} — {s.balance} б." for i, s in enumerate(top_fac, 1))

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="my_profile")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ── Статистика заданий (модератор) ───────────────────────────────────────────

@router.callback_query(F.data == "task_stats_menu")
async def task_stats_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    with Session() as session:
        total_done = session.execute(text("SELECT COUNT(*) FROM task_verifications WHERE status = 'approved'")).scalar()
        tasks = session.query(Task).filter_by(is_deleted=False).all()

    buttons = [[InlineKeyboardButton(text=f"📝 {t.title}", callback_data=f"task_stat_{t.id}")] for t in tasks]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        f"📝 *Статистика заданий*\nВсего выполнено: {total_done}\n\nВыбери задание:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("task_stat_"))
async def task_stat_detail(callback: CallbackQuery):
    task_id = int(callback.data.split("_")[2])
    with Session() as session:
        task = session.query(Task).get(task_id)
        approved = session.execute(text("SELECT COUNT(*) FROM task_verifications WHERE task_id=:id AND status='approved'"), {"id": task_id}).scalar()
        pending  = session.execute(text("SELECT COUNT(*) FROM task_verifications WHERE task_id=:id AND status='pending'"),  {"id": task_id}).scalar()
        rejected = session.execute(text("SELECT COUNT(*) FROM task_verifications WHERE task_id=:id AND status='rejected'"), {"id": task_id}).scalar()
        recent = session.execute(text("""
            SELECT s.full_name, tv.submitted_at FROM task_verifications tv
            JOIN students s ON s.id = tv.student_id
            WHERE tv.task_id=:id AND tv.status='approved' ORDER BY tv.submitted_at DESC LIMIT 5
        """), {"id": task_id}).fetchall()

    msg = f"📌 *{task.title}*\n\n✅ Выполнили: {approved}\n⏳ На проверке: {pending}\n❌ Отклонено: {rejected}\n"
    if recent:
        msg += "\n*Последние:*\n" + "".join(f"• {n} — {d.strftime('%d.%m %H:%M')}\n" for n, d in recent)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="task_stats_menu")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


# ── Статистика магазина (модератор) ──────────────────────────────────────────

@router.callback_query(F.data == "shop_stats_menu")
async def shop_stats_menu(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав", show_alert=True)
    with Session() as session:
        total_p = session.execute(text("SELECT COUNT(*) FROM purchases")).scalar()
        total_s = session.execute(text("SELECT COALESCE(SUM(total_points),0) FROM purchases")).scalar()
        items = session.query(Merchandise).filter_by(is_deleted=False).all()

    buttons = [[InlineKeyboardButton(text=f"🛍 {m.name}", callback_data=f"shop_stat_{m.id}")] for m in items]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        f"🛍 *Статистика магазина*\nПокупок: {total_p} | Баллов: {total_s}\n\nВыбери товар:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("shop_stat_"))
async def shop_stat_detail(callback: CallbackQuery):
    item_id = int(callback.data.split("_")[2])
    with Session() as session:
        item = session.query(Merchandise).get(item_id)
        bought = session.execute(text("SELECT COUNT(*) FROM purchases WHERE merch_id=:id"), {"id": item_id}).scalar()
        spent  = session.execute(text("SELECT COALESCE(SUM(total_points),0) FROM purchases WHERE merch_id=:id"), {"id": item_id}).scalar()
        recent = session.execute(text("""
            SELECT s.full_name, p.purchased_at FROM purchases p JOIN students s ON s.id=p.student_id
            WHERE p.merch_id=:id ORDER BY p.purchased_at DESC LIMIT 5
        """), {"id": item_id}).fetchall()

    msg = f"🛍 *{item.name}*\n\n🛒 Куплено: {bought}\n💰 Баллов: {spent}\n📦 Остаток: {item.stock}\n"
    if recent:
        msg += "\n*Последние:*\n" + "".join(f"• {n} — {d.strftime('%d.%m %H:%M')}\n" for n, d in recent)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="shop_stats_menu")]])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=kb)


@router.callback_query(F.data == "stats")
async def show_admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав")
    with Session() as session:
        total = session.query(Student).count()
        active_s = session.query(Student).filter_by(status="active").count()
        tasks_done = session.execute(text("SELECT COUNT(*) FROM task_verifications WHERE status='approved'")).scalar()
        purchases  = session.execute(text("SELECT COUNT(*) FROM purchases")).scalar()
        active_ev  = session.query(Event).filter_by(status='active').count()
        total_parts= session.execute(text("SELECT COUNT(*) FROM event_participants")).scalar()

    msg = (
        f"📊 *Статистика системы*\n\n"
        f"👥 Студентов: {total} (активных: {active_s})\n"
        f"📝 Заданий выполнено: {tasks_done}\n"
        f"🛍 Покупок: {purchases}\n"
        f"🎪 Активных мероприятий: {active_ev}\n"
        f"👥 Регистраций: {total_parts}\n"
    )
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=BACK_KB)
