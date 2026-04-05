# handlers/tasks.py — поддержка видео-доказательств
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import Session
from models import Student, Task, TaskVerification
from states import TaskState
from config import ADMIN_IDS
from keyboards import main_menu_keyboard

router = Router()
PAGE_SIZE = 5
MOSCOW_OFFSET = timedelta(hours=3)


def _now_moscow():
    return datetime.utcnow() + MOSCOW_OFFSET


def _task_status_emoji(verif) -> str:
    if verif is None: return "❌"
    if verif.status == "approved": return "✅"
    if verif.status == "pending": return "⏳"
    return "❌"


def _deadline_suffix(task: Task, is_admin: bool) -> str:
    if not task.deadline: return ""
    now = _now_moscow()
    if task.deadline < now: return " ⏰ 0м"
    if not is_admin and not task.show_deadline: return ""
    delta = task.deadline - now
    total_mins = int(delta.total_seconds() // 60)
    if total_mins >= 1440: return f" ⏰ {total_mins // 1440}д"
    if total_mins >= 60:
        h, m = total_mins // 60, total_mins % 60
        return f" ⏰ {h}ч {m}м"
    return f" ⏰ {total_mins}м"


def _build_tasks_kb(tasks, verifs, page, total, is_admin) -> InlineKeyboardMarkup:
    buttons = []
    for t in tasks:
        v = verifs.get(t.id)
        emoji = _task_status_emoji(v)
        suffix = _deadline_suffix(t, is_admin)
        buttons.append([InlineKeyboardButton(text=f"{emoji} {t.title} — {t.points} б.{suffix}", callback_data=f"task_{t.id}")])

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="◀️", callback_data=f"tasks_page_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop_task"))
    if (page+1)*PAGE_SIZE < total: nav.append(InlineKeyboardButton(text="▶️", callback_data=f"tasks_page_{page+1}"))
    if len(nav) > 1: buttons.append(nav)

    if is_admin:
        buttons.append([InlineKeyboardButton(text="➕ Добавить задание", callback_data="add_task")])
        buttons.append([InlineKeyboardButton(text="📝 Статистика заданий", callback_data="task_stats_menu")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _show_tasks_page(target, page, user_id):
    now = _now_moscow()
    is_admin = user_id in ADMIN_IDS
    with Session() as session:
        all_tasks = session.query(Task).filter(
            Task.is_deleted == False,
            (Task.deadline == None) | (Task.deadline > now)
        ).order_by(Task.created_at).all()
        total = len(all_tasks)
        page_tasks = all_tasks[page*PAGE_SIZE:(page+1)*PAGE_SIZE]
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        verifs = {}
        if student:
            for t in page_tasks:
                v = session.query(TaskVerification).filter_by(student_id=student.id, task_id=t.id).first()
                if v: verifs[t.id] = v

    kb = _build_tasks_kb(page_tasks, verifs, page, total, is_admin)
    text = f"📄 Задания ({total} шт.):" if page_tasks else "📄 Заданий пока нет."
    if isinstance(target, CallbackQuery):
        try: await target.message.delete()
        except Exception: pass
        await target.message.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "menu_tasks")
async def open_tasks_menu(callback: CallbackQuery, state: FSMContext):
    await _show_tasks_page(callback, 0, callback.from_user.id)


@router.callback_query(F.data.startswith("tasks_page_"))
async def tasks_page(callback: CallbackQuery):
    await _show_tasks_page(callback, int(callback.data.split("_")[2]), callback.from_user.id)


@router.callback_query(F.data == "noop_task")
async def noop_task(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("task_") & ~F.data.startswith("tasks_page_") & ~F.data.startswith("task_stat"))
async def view_task(callback: CallbackQuery, state: FSMContext):
    raw = callback.data[5:]
    if not raw.isdigit(): return
    task_id = int(raw)
    user_id = callback.from_user.id
    now = _now_moscow()
    is_admin = user_id in ADMIN_IDS

    with Session() as session:
        task = session.query(Task).get(task_id)
        if not task or task.is_deleted: return await callback.answer("Задание не найдено")
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        verification = session.query(TaskVerification).filter_by(student_id=student.id if student else -1, task_id=task_id).first() if student else None

    is_expired = task.deadline and task.deadline < now
    msg = (
        f"{_task_status_emoji(verification)} *{task.title}*\n\n"
        f"{task.description or ''}\n\n"
        f"💯 Баллов: {task.points}\n"
        f"🔍 Проверка: {'по ответу' if task.verification_type == 'auto' else 'по доказательству'}"
    )
    if task.deadline and (is_admin or task.show_deadline):
        msg += f"\n⏰ Дедлайн: {task.deadline.strftime('%d.%m.%Y %H:%M')} МСК"

    buttons = []
    if is_expired: msg += "\n\n🔒 Завершено"
    elif verification and verification.status == "approved": msg += "\n\n✅ Уже выполнено"
    elif verification and verification.status == "pending": msg += "\n\n⏳ На проверке"
    else: buttons.append([InlineKeyboardButton(text="✍️ Выполнить", callback_data=f"do_task_{task_id}")])

    if is_admin: buttons.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_task_{task_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_tasks")])

    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("del_task_"))
async def delete_task(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав")
    task_id = int(callback.data.split("_")[2])
    with Session() as session:
        task = session.query(Task).get(task_id)
        if task: task.is_deleted = True; session.commit()
    await callback.answer("🗑 Удалено")
    await _show_tasks_page(callback, 0, callback.from_user.id)


@router.callback_query(F.data.startswith("do_task_"))
async def start_task(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[2])
    with Session() as session:
        task = session.query(Task).get(task_id)
        if not task: return await callback.answer("Задание не найдено")
    await state.update_data(task_id=task_id)
    if task.verification_type == "auto":
        await callback.message.answer("✏️ Введите ваш ответ:")
        await state.set_state(TaskState.waiting_answer)
    else:
        hint = task.proof_text or "Отправьте доказательство (текст, фото или видео)"
        await callback.message.answer(f"📤 {hint}")
        await state.set_state(TaskState.waiting_proof)


@router.message(TaskState.waiting_answer)
async def receive_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")
    if not task_id: await state.clear(); return await message.answer("❗ Начни заново.")
    user_id = message.from_user.id
    with Session() as session:
        task = session.query(Task).get(task_id)
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student: await state.clear(); return await message.answer("❌ Не зарегистрирован.")
        if message.text.strip().lower() == (task.correct_answer or "").strip().lower():
            student.balance += task.points
            session.add(TaskVerification(student_id=student.id, task_id=task_id, proof_text=message.text.strip(), status="approved"))
            session.commit()
            await state.clear()
            await message.answer(f"✅ Правильно! +{task.points} баллов.", reply_markup=main_menu_keyboard(user_id in ADMIN_IDS))
        else:
            await message.answer("❌ Неверный ответ. Попробуй ещё раз:")


@router.message(TaskState.waiting_proof)
async def receive_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")
    if not task_id: await state.clear(); return await message.answer("❗ Начни заново.")
    user_id = message.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student: await state.clear(); return await message.answer("❌ Не зарегистрирован.")

        proof_text = message.text or message.caption or ""
        file_id = None
        proof_type = "photo"

        if message.photo:
            file_id = message.photo[-1].file_id
            proof_type = "photo"
        elif message.video:
            file_id = message.video.file_id
            proof_type = "video"
        elif message.document:
            file_id = message.document.file_id
            proof_type = "document"

        session.add(TaskVerification(
            student_id=student.id, task_id=task_id,
            proof_text=proof_text, proof_file=file_id,
            proof_type=proof_type, status="pending"
        ))
        session.commit()
    await state.clear()
    await message.answer("📨 Отправлено на проверку.", reply_markup=main_menu_keyboard(user_id in ADMIN_IDS))


# ── Модерация ─────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "menu_moderation")
async def show_moderation(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав")
    with Session() as session:
        pending = session.query(TaskVerification).filter_by(status="pending").all()
        if not pending:
            try: await callback.message.delete()
            except Exception: pass
            return await callback.message.answer("📑 Нет заданий на проверке.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]]))
        buttons = []
        for v in pending:
            student = session.query(Student).get(v.student_id)
            task = session.query(Task).get(v.task_id)
            if student and task:
                buttons.append([InlineKeyboardButton(text=f"👤 {student.full_name} — {task.title}", callback_data=f"moderate_{v.id}")])
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(f"📑 На проверке: {len(pending)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("moderate_"))
async def view_verification(callback: CallbackQuery):
    v_id = int(callback.data.split("_")[1])
    with Session() as session:
        v = session.query(TaskVerification).get(v_id)
        if not v: return await callback.answer("Не найдено")
        student = session.query(Student).get(v.student_id)
        task = session.query(Task).get(v.task_id)
        proof_file = v.proof_file
        proof_type = v.proof_type or "photo"
        msg = f"👤 {student.full_name}\n📌 {task.title} (+{task.points} б.)\n\n📝 {v.proof_text or '(нет текста)'}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{v_id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{v_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_moderation")],
        ])
    try: await callback.message.delete()
    except Exception: pass
    if proof_file:
        if proof_type == "video":
            await callback.message.answer_video(video=proof_file, caption=msg, reply_markup=kb)
        elif proof_type == "document":
            await callback.message.answer_document(document=proof_file, caption=msg, reply_markup=kb)
        else:
            await callback.message.answer_photo(photo=proof_file, caption=msg, reply_markup=kb)
    else:
        await callback.message.answer(msg, reply_markup=kb)


@router.callback_query(F.data.startswith("approve_"))
async def approve_verification(callback: CallbackQuery, bot: Bot):
    v_id = int(callback.data.split("_")[1])
    with Session() as session:
        v = session.query(TaskVerification).get(v_id)
        if not v or v.status != "pending": return await callback.answer("Уже обработано")
        student = session.query(Student).get(v.student_id)
        task = session.query(Task).get(v.task_id)
        v.status = "approved"; student.balance += task.points; session.commit()
        tg, title, pts = student.telegram_id, task.title, task.points
    await callback.answer("✅ Принято!")
    if tg:
        try: await bot.send_message(tg, f"🎉 Задание «{title}» принято! +{pts} баллов.")
        except Exception: pass
    await show_moderation(callback)


@router.callback_query(F.data.startswith("reject_"))
async def reject_verification(callback: CallbackQuery, bot: Bot):
    v_id = int(callback.data.split("_")[1])
    with Session() as session:
        v = session.query(TaskVerification).get(v_id)
        if not v or v.status != "pending": return await callback.answer("Уже обработано")
        student = session.query(Student).get(v.student_id)
        task = session.query(Task).get(v.task_id)
        v.status = "rejected"; session.commit()
        tg, title = student.telegram_id, task.title
    await callback.answer("❌ Отклонено")
    if tg:
        try: await bot.send_message(tg, f"😔 Задание «{title}» отклонено.")
        except Exception: pass
    await show_moderation(callback)


# ── Добавление задания ────────────────────────────────────────────────────────
@router.callback_query(F.data == "add_task")
async def add_task_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return await callback.answer("⛔ Нет прав")
    await callback.message.answer("📌 Название задания:")
    await state.set_state(TaskState.AWAITING_TITLE)


@router.message(TaskState.AWAITING_TITLE)
async def get_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("📝 Описание:")
    await state.set_state(TaskState.AWAITING_DESCRIPTION)


@router.message(TaskState.AWAITING_DESCRIPTION)
async def get_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("💯 Баллы:")
    await state.set_state(TaskState.AWAITING_POINTS)


@router.message(TaskState.AWAITING_POINTS)
async def get_points(message: Message, state: FSMContext):
    if not message.text.strip().isdigit(): return await message.answer("❗ Число")
    await state.update_data(points=int(message.text.strip()))
    await message.answer("Тип проверки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✏️ По ответу", callback_data="check_type:auto"),
        InlineKeyboardButton(text="📷 По доказательству", callback_data="check_type:manual"),
    ]]))
    await state.set_state(TaskState.AWAITING_CHECK_TYPE)


@router.callback_query(F.data.startswith("check_type:"))
async def get_check_type(callback: CallbackQuery, state: FSMContext):
    vtype = callback.data.split(":", 1)[1]
    await state.update_data(verification_type=vtype)
    if vtype == "auto":
        await callback.message.answer("✏️ Правильный ответ:")
        await state.set_state(TaskState.AWAITING_CORRECT_ANSWER)
    else:
        await callback.message.answer("📤 Подсказка для доказательства:")
        await state.set_state(TaskState.AWAITING_PROOF_TEXT)


@router.message(TaskState.AWAITING_CORRECT_ANSWER)
async def get_correct_answer(message: Message, state: FSMContext):
    await state.update_data(correct_answer=message.text.strip())
    await _ask_deadline(message, state)


@router.message(TaskState.AWAITING_PROOF_TEXT)
async def get_proof_text(message: Message, state: FSMContext):
    await state.update_data(proof_text=message.text.strip())
    await _ask_deadline(message, state)


async def _ask_deadline(message, state):
    await message.answer("Дедлайн?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏰ Установить", callback_data="set_deadline")],
        [InlineKeyboardButton(text="♾ Без дедлайна", callback_data="no_deadline")],
    ]))
    await state.set_state(TaskState.AWAITING_PROOF_FILE)


@router.callback_query(F.data == "no_deadline")
async def no_deadline(callback: CallbackQuery, state: FSMContext):
    await state.update_data(deadline=None, show_deadline=False)
    await _finish_task(callback.message, state)


@router.callback_query(F.data == "set_deadline")
async def ask_deadline_input(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("⏰ ДД.ММ.ГГГГ ЧЧ:ММ (МСК):")
    await state.set_state(TaskState.AWAITING_DEADLINE)


@router.message(TaskState.AWAITING_DEADLINE)
async def receive_deadline_input(message: Message, state: FSMContext):
    try:
        deadline = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
        await state.update_data(deadline=deadline)
        await message.answer("Показывать время пользователям?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="show_dl_yes")],
            [InlineKeyboardButton(text="🙈 Нет", callback_data="show_dl_no")],
        ]))
        await state.set_state(TaskState.AWAITING_SHOW_DEADLINE)
    except ValueError:
        await message.answer("❗ Формат: 31.12.2025 23:59")


@router.callback_query(F.data == "show_dl_yes")
async def show_dl_yes(callback: CallbackQuery, state: FSMContext):
    await state.update_data(show_deadline=True)
    await _finish_task(callback.message, state)


@router.callback_query(F.data == "show_dl_no")
async def show_dl_no(callback: CallbackQuery, state: FSMContext):
    await state.update_data(show_deadline=False)
    await _finish_task(callback.message, state)


async def _finish_task(message, state):
    data = await state.get_data()
    with Session() as session:
        session.add(Task(
            title=data["title"], description=data["description"],
            points=data["points"], verification_type=data["verification_type"],
            correct_answer=data.get("correct_answer"), proof_text=data.get("proof_text"),
            deadline=data.get("deadline"), show_deadline=data.get("show_deadline", False),
        ))
        session.commit()
    await state.clear()
    await message.answer("✅ Задание добавлено.", reply_markup=main_menu_keyboard(message.chat.id in ADMIN_IDS))
