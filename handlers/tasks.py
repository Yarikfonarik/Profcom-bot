# handlers/tasks.py
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from database import Session
from models import Student, Task, TaskVerification
from states import TaskState
from config import ADMIN_IDS
from keyboards import main_menu_keyboard

router = Router()


# ── Список заданий ──────────────────────────────────────────────────────────
@router.callback_query(F.data == "menu_tasks")
async def open_tasks_menu(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    with Session() as session:
        tasks = session.query(Task).all()

    buttons = [
        [InlineKeyboardButton(text=f"{t.title} — {t.points} баллов", callback_data=f"task_{t.id}")]
        for t in tasks
    ]
    if user_id in ADMIN_IDS:
        buttons.append([InlineKeyboardButton(text="➕ Добавить задание", callback_data="add_task")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")])

    await callback.message.edit_text(
        "📄 Задания:" if tasks else "📄 Заданий пока нет.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ── Просмотр задания ────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("task_"))
async def view_task(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id

    with Session() as session:
        task = session.query(Task).get(task_id)
        if not task:
            return await callback.answer("Задание не найдено")

        student = session.query(Student).filter_by(telegram_id=user_id).first()
        already_done = False
        if student:
            already_done = session.query(TaskVerification).filter_by(
                student_id=student.id,
                task_id=task_id,
                status="approved"
            ).first() is not None

    msg = (
        f"📌 {task.title}\n\n"
        f"{task.description or ''}\n\n"
        f"💯 Баллов за выполнение: {task.points}\n"
        f"🔍 Тип проверки: {'по ответу' if task.verification_type == 'auto' else 'по доказательству'}"
    )

    buttons = []
    if already_done:
        msg += "\n\n✅ Ты уже выполнил это задание"
    else:
        buttons.append([InlineKeyboardButton(text="✍️ Выполнить задание", callback_data=f"do_task_{task_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_tasks")])

    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ── Начало выполнения задания ───────────────────────────────────────────────
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
        hint = task.proof_text or "Отправьте доказательство выполнения (текст или фото)"
        await callback.message.answer(f"📤 {hint}")
        await state.set_state(TaskState.waiting_proof)


# ── Приём ответа ────────────────────────────────────────────────────────────
@router.message(TaskState.waiting_answer)
async def receive_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")

    if not task_id:
        await state.clear()
        return await message.answer("❗ Что-то пошло не так. Начни заново через меню.")

    user_id = message.from_user.id

    with Session() as session:
        task = session.query(Task).get(task_id)
        student = session.query(Student).filter_by(telegram_id=user_id).first()

        if not student:
            await state.clear()
            return await message.answer("❌ Ты не зарегистрирован.")

        answer = message.text.strip().lower()
        correct = (task.correct_answer or "").strip().lower()

        if answer == correct:
            student.balance += task.points
            verification = TaskVerification(
                student_id=student.id,
                task_id=task_id,
                proof_text=message.text.strip(),
                status="approved"
            )
            session.add(verification)
            session.commit()
            await state.clear()
            is_admin = user_id in ADMIN_IDS
            await message.answer(
                f"✅ Правильно! Тебе начислено {task.points} баллов.",
                reply_markup=main_menu_keyboard(is_admin)
            )
        else:
            await message.answer("❌ Неверный ответ. Попробуй ещё раз:")


# ── Приём доказательства ────────────────────────────────────────────────────
@router.message(TaskState.waiting_proof)
async def receive_proof(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("task_id")

    if not task_id:
        await state.clear()
        return await message.answer("❗ Что-то пошло не так. Начни заново через меню.")

    user_id = message.from_user.id

    with Session() as session:
        student = session.query(Student).filter_by(telegram_id=user_id).first()
        if not student:
            await state.clear()
            return await message.answer("❌ Ты не зарегистрирован.")

        proof_text = message.text or message.caption or ""
        proof_file = message.photo[-1].file_id if message.photo else None

        verification = TaskVerification(
            student_id=student.id,
            task_id=task_id,
            proof_text=proof_text,
            proof_file=proof_file,
            status="pending"
        )
        session.add(verification)
        session.commit()

    await state.clear()
    is_admin = user_id in ADMIN_IDS
    await message.answer(
        "📨 Доказательство отправлено на проверку модератору.",
        reply_markup=main_menu_keyboard(is_admin)
    )


# ── Добавление задания (для админа) ────────────────────────────────────────
@router.callback_query(F.data == "add_task")
async def add_task_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ У вас нет прав")
    await callback.message.answer("📌 Введите название задания:")
    await state.set_state(TaskState.AWAITING_TITLE)


@router.message(TaskState.AWAITING_TITLE)
async def get_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("📝 Введите описание задания:")
    await state.set_state(TaskState.AWAITING_DESCRIPTION)


@router.message(TaskState.AWAITING_DESCRIPTION)
async def get_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("💯 Введите количество баллов за выполнение:")
    await state.set_state(TaskState.AWAITING_POINTS)


@router.message(TaskState.AWAITING_POINTS)
async def get_points(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите целое число")
    await state.update_data(points=int(message.text.strip()))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ По ответу",        callback_data="check_type:auto"),
            InlineKeyboardButton(text="📷 По доказательству", callback_data="check_type:manual"),
        ]
    ])
    await message.answer("Выберите тип проверки:", reply_markup=kb)
    await state.set_state(TaskState.AWAITING_CHECK_TYPE)


@router.callback_query(F.data.startswith("check_type:"))
async def get_check_type(callback: CallbackQuery, state: FSMContext):
    vtype = callback.data.split(":", 1)[1]
    await state.update_data(verification_type=vtype)

    if vtype == "auto":
        await callback.message.answer("✏️ Введите правильный ответ:")
        await state.set_state(TaskState.AWAITING_CORRECT_ANSWER)
    else:
        await callback.message.answer("📤 Введите подсказку для доказательств:")
        await state.set_state(TaskState.AWAITING_PROOF_TEXT)


@router.message(TaskState.AWAITING_CORRECT_ANSWER)
async def get_correct_answer(message: Message, state: FSMContext):
    await state.update_data(correct_answer=message.text.strip())
    await finish_task_creation(message, state)


@router.message(TaskState.AWAITING_PROOF_TEXT)
async def get_proof_text(message: Message, state: FSMContext):
    await state.update_data(proof_text=message.text.strip())
    await finish_task_creation(message, state)


async def finish_task_creation(message: Message, state: FSMContext):
    data = await state.get_data()
    with Session() as session:
        new_task = Task(
            title=data["title"],
            description=data["description"],
            points=data["points"],
            verification_type=data["verification_type"],
            correct_answer=data.get("correct_answer"),
            proof_text=data.get("proof_text"),
        )
        session.add(new_task)
        session.commit()

    await state.clear()
    is_admin = message.from_user.id in ADMIN_IDS
    await message.answer("✅ Задание успешно добавлено.", reply_markup=main_menu_keyboard(is_admin))