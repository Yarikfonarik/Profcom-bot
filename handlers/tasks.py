# handlers/tasks.py
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
    if verif is None:
        return "❌"
    if verif.status == "approved":
        return "✅"
    if verif.status == "pending":
        return "⏳"
    return "❌"


def _deadline_icon(task: Task) -> str:
    """Возвращает иконку дедлайна для всех пользователей."""
    if not task.deadline:
        return ""
    now = _now_moscow()
    if task.deadline < now:
        return " 🔒"
    delta = task.deadline - now
    hours = int(delta.total_seconds() // 3600)
    if hours < 3:
        return " 🔥"   # горит — меньше 3 часов
    if hours < 24:
        return " ⏰"   # скоро
    return " 📅"       # есть время


def _build_tasks_kb(tasks, verifs: dict, page: int, total: int, is_admin: bool) -> InlineKeyboardMarkup:
    buttons = []
    for t in tasks:
        v = verifs.get(t.id)
        emoji = _task_status_emoji(v)
        deadline_icon = _deadline_icon(t)
        label = f"{emoji} {t.title} — {t.points} б.{deadline_icon}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"task_{t.id}")])

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"tasks_page_{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"tasks_page_{page + 1}"))
    if len(nav) > 1:
        buttons.append(nav)

    if is_admin:
        buttons.append([InlineKeyboardButton(text="➕ Добавить задание", callback_data="add_task")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _show_tasks_page(target, page: int, user_id: int):
    now = _now_moscow()
    with Session() as session:
        all_tasks = session.query(Task).filter(
            Task.is_deleted == False,
            (Task.deadline == None) | (Task.deadline > now)
        ).order_by(Task.created_at).all()

        total = len(all_tasks)
        page_tasks = all_tasks[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

        student = session.query(Student).filter_by(telegram_id=user_id).first()
        verifs = {}
        if student:
            for t in page_tasks:
                v = session.query(TaskVerification).filter_by(student_id=student.id, task_id=t.id).first()
                if v:
                    verifs[t.id] = v

    is_admin = user_id in ADMIN_IDS
    kb = _build_tasks_kb(page_tasks, verifs, page, total, is_admin)
    text = f"📄 Задания ({total} шт.):" if page_tasks else "📄 Заданий пока нет."

    if isinstance(target, CallbackQuery):
        try:
            await target.message.delete()
        except Exception:
            pass
        await target.message.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "menu_tasks")
async def open_tasks_menu(callback: CallbackQuery, state: FSMContext):
    await _show_tasks_page(callback, 0, callback.from_user.id)


@router.callback_query(F.data.startswith("tasks_page_"))
async def tasks_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[2])
    await _show_tasks_page(callback, page, callback.from_user.id)


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data.startswith("task_") & ~F.data.startswith("tasks_page_"))
async def view_task(callback: CallbackQuery, state: FSMContext):
    raw = callback.data[5:]
    if not raw.isdigit():
        return
    task_id = int(raw)
    user_id = callback.from_user.id
    now = _now_moscow()
    is_admin = user_id in ADMIN_IDS

    with Session() as session:
        task = session.query(Task).get(task_id)
        if not task or task.is_deleted:
            return await callback.answer("Задание не найдено")
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        verification = None
        if student:
            verification = session.query(TaskVerification).filter_by(student_id=student.id, task_id=task_id).first()

    is_expired = task.deadline and task.deadline < now
    status_emoji = _task_status_emoji(verification)

    msg = (
        f"{status_emoji} *{task.title}*\n\n"
        f"{task.description or ''}\n\n"
        f"💯 Баллов: {task.points}\n"
        f"🔍 Проверка: {'по ответу' if task.verification_type == 'auto' else 'по доказательству'}"
    )

    # Дедлайн — только точное время для админа
    if task.deadline:
        if is_admin:
            msg += f"\n⏰ Дедлайн: {task.deadline.strftime('%d.%m.%Y %H:%M')} МСК"

    buttons = []
    if is_expired:
        msg += "\n\n🔒 Задание завершено"
    elif verification and verification.status == "approved":
        msg += "\n\n✅ Ты уже выполнил это задание"
    elif verification and verification.status == "pending":
        msg += "\n\n⏳ Доказательство на проверке"
    else:
        buttons.append([InlineKeyboardButton(text="✍️ Выполнить", callback_data=f"do_task_{task_id}")])

    if is_admin:
        buttons.append([InlineKeyboardButton(text="🗑 Удалить задание", callback_data=f"del_task_{task_id}")])

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_tasks")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("del_task_"))
async def delete_task(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")
    task_id = int(callback.data.split("_")[2])
    with Session() as session:
        task = session.query(Task).get(task_id)
        if task:
            task.is_deleted = True
            session.commit()
    await callback.answer("🗑 Задание удалено")
    await _show_tasks_page(callback, 0, callback.from_user.id)


@router.callback_query(F.data.startswith("do_task_"))
async def start_task(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[2])
    with Session() as session:
        task = session.query(Task).get(task_id)
        if not task:
            return await callback.answer("Задание не найдено")
    await state.update_data(task_id=task_id)
    if task.verification_type == "auto":
        await callback.message.answer("✏️ Введите ваш ответ:")
        await state.set_state(TaskState.waiting_answer)
    else:
        await callback.message.answer(f"📤 {task.proof_text or 'Отправьте доказательство (текст или фото)'}")
        await state.set_state(TaskState.waiting_proof)


@router.message(TaskState.waiting_answer)
async def receive_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")
    if not task_id:
        await state.clear()
        return await message.answer("❗ Начни заново через меню.")
    user_id = message.from_user.id
    with Session() as session:
        task = session.query(Task).get(task_id)
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            await state.clear()
            return await message.answer("❌ Ты не зарегистрирован.")
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
    if not task_id:
        await state.clear()
        return await message.answer("❗ Начни заново через меню.")
    user_id = message.from_user.id
    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            await state.clear()
            return await message.answer("❌ Ты не зарегистрирован.")
        proof_text = message.text or message.caption or ""
        proof_file = message.photo[-1].file_id if message.photo else None
        session.add(TaskVerification(student_id=student.id, task_id=task_id, proof_text=proof_text, proof_file=proof_file, status="pending"))
        session.commit()
    await state.clear()
    await message.answer("📨 Отправлено на проверку.", reply_markup=main_menu_keyboard(user_id in ADMIN_IDS))


@router.callback_query(F.data == "menu_moderation")
async def show_moderation(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")
    with Session() as session:
        pending = session.query(TaskVerification).filter_by(status="pending").all()
        if not pending:
            try:
                await callback.message.delete()
            except Exception:
                pass
            return await callback.message.answer(
                "📑 Нет заданий на проверке.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]])
            )
        buttons = []
        for v in pending:
            student = session.query(Student).get(v.student_id)
            task = session.query(Task).get(v.task_id)
            if student and task:
                buttons.append([InlineKeyboardButton(text=f"👤 {student.full_name} — {task.title}", callback_data=f"moderate_{v.id}")])
        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(f"📑 На проверке: {len(pending)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(F.data.startswith("moderate_"))
async def view_verification(callback: CallbackQuery):
    v_id = int(callback.data.split("_")[1])
    with Session() as session:
        v = session.query(TaskVerification).get(v_id)
        if not v:
            return await callback.answer("Не найдено")
        student = session.query(Student).get(v.student_id)
        task = session.query(Task).get(v.task_id)
        msg = f"👤 {student.full_name}\n📌 {task.title} (+{task.points} б.)\n\n📝 {v.proof_text or '(нет текста)'}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{v_id}"),
             InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{v_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_moderation")],
        ])
        proof_file = v.proof_file
    try:
        await callback.message.delete()
    except Exception:
        pass
    if proof_file:
        await callback.message.answer_photo(photo=proof_file, caption=msg, reply_markup=kb)
    else:
        await callback.message.answer(msg, reply_markup=kb)


@router.callback_query(F.data.startswith("approve_"))
async def approve_verification(callback: CallbackQuery, bot: Bot):
    v_id = int(callback.data.split("_")[1])
    with Session() as session:
        v = session.query(TaskVerification).get(v_id)
        if not v or v.status != "pending":
            return await callback.answer("Уже обработано")
        student = session.query(Student).get(v.student_id)
        task = session.query(Task).get(v.task_id)
        v.status = "approved"
        student.balance += task.points
        session.commit()
        tg, title, pts = student.telegram_id, task.title, task.points
    await callback.answer("✅ Принято!")
    if tg:
        try:
            await bot.send_message(tg, f"🎉 Задание «{title}» принято! +{pts} баллов.")
        except Exception:
            pass
    await show_moderation(callback)


@router.callback_query(F.data.startswith("reject_"))
async def reject_verification(callback: CallbackQuery, bot: Bot):
    v_id = int(callback.data.split("_")[1])
    with Session() as session:
        v = session.query(TaskVerification).get(v_id)
        if not v or v.status != "pending":
            return await callback.answer("Уже обработано")
        student = session.query(Student).get(v.student_id)
        task = session.query(Task).get(v.task_id)
        v.status = "rejected"
        session.commit()
        tg, title = student.telegram_id, task.title
    await callback.answer("❌ Отклонено")
    if tg:
        try:
            await bot.send_message(tg, f"😔 Задание «{title}» отклонено.")
        except Exception:
            pass
    await show_moderation(callback)


@router.callback_query(F.data == "add_task")
async def add_task_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ Нет прав")
    await callback.message.answer("📌 Введите название задания:")
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
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите число")
    await state.update_data(points=int(message.text.strip()))
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✏️ По ответу", callback_data="check_type:auto"),
        InlineKeyboardButton(text="📷 По доказательству", callback_data="check_type:manual"),
    ]])
    await message.answer("Тип проверки:", reply_markup=kb)
    await state.set_state(TaskState.AWAITING_CHECK_TYPE)


@router.callback_query(F.data.startswith("check_type:"))
async def get_check_type(callback: CallbackQuery, state: FSMContext):
    vtype = callback.data.split(":", 1)[1]
    await state.update_data(verification_type=vtype)
    if vtype == "auto":
        await callback.message.answer("✏️ Введите правильный ответ:")
        await state.set_state(TaskState.AWAITING_CORRECT_ANSWER)
    else:
        await callback.message.answer("📤 Введите подсказку:")
        await state.set_state(TaskState.AWAITING_PROOF_TEXT)


@router.message(TaskState.AWAITING_CORRECT_ANSWER)
async def get_correct_answer(message: Message, state: FSMContext):
    await state.update_data(correct_answer=message.text.strip())
    await _ask_deadline(message, state)


@router.message(TaskState.AWAITING_PROOF_TEXT)
async def get_proof_text(message: Message, state: FSMContext):
    await state.update_data(proof_text=message.text.strip())
    await _ask_deadline(message, state)


async def _ask_deadline(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏰ Установить дедлайн", callback_data="set_deadline")],
        [InlineKeyboardButton(text="♾ Без дедлайна",        callback_data="no_deadline")],
    ])
    await message.answer("Установить дедлайн?", reply_markup=kb)
    await state.set_state(TaskState.AWAITING_PROOF_FILE)


@router.callback_query(F.data == "no_deadline")
async def no_deadline(callback: CallbackQuery, state: FSMContext):
    await state.update_data(deadline=None)
    await _finish_task(callback.message, state)


@router.callback_query(F.data == "set_deadline")
async def ask_deadline_input(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("⏰ Введите дату МСК:\nДД.ММ.ГГГГ ЧЧ:ММ\n\nПример: 31.12.2025 23:59")
    await state.set_state(TaskState.AWAITING_DEADLINE)


@router.message(TaskState.AWAITING_DEADLINE)
async def receive_deadline_input(message: Message, state: FSMContext):
    try:
        deadline = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
        await state.update_data(deadline=deadline)
        await _finish_task(message, state)
    except ValueError:
        await message.answer("❗ Формат: 31.12.2025 23:59")


async def _finish_task(message: Message, state: FSMContext):
    data = await state.get_data()
    with Session() as session:
        session.add(Task(
            title=data["title"], description=data["description"],
            points=data["points"], verification_type=data["verification_type"],
            correct_answer=data.get("correct_answer"), proof_text=data.get("proof_text"),
            deadline=data.get("deadline"),
        ))
        session.commit()
    await state.clear()
    await message.answer("✅ Задание добавлено.", reply_markup=main_menu_keyboard(message.from_user.id in ADMIN_IDS))
