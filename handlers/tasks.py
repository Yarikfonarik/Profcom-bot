# handlers/tasks.py
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from database import Session
from models import Student, Task, TaskVerification
from states import TaskState
from config import ADMIN_IDS
from keyboards import main_menu_keyboard

router = Router()


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

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "📄 Задания:" if tasks else "📄 Заданий пока нет.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


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
        pending = False
        if student:
            verification = session.query(TaskVerification).filter_by(
                student_id=student.id, task_id=task_id
            ).first()
            if verification:
                already_done = verification.status == "approved"
                pending = verification.status == "pending"

    msg = (
        f"📌 {task.title}\n\n"
        f"{task.description or ''}\n\n"
        f"💯 Баллов: {task.points}\n"
        f"🔍 Проверка: {'по ответу' if task.verification_type == 'auto' else 'по доказательству'}"
    )

    buttons = []
    if already_done:
        msg += "\n\n✅ Ты уже выполнил это задание"
    elif pending:
        msg += "\n\n⏳ Твоё доказательство на проверке"
    else:
        buttons.append([InlineKeyboardButton(text="✍️ Выполнить", callback_data=f"do_task_{task_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_tasks")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


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

        answer = message.text.strip().lower()
        correct = (task.correct_answer or "").strip().lower()

        if answer == correct:
            student.balance += task.points
            session.add(TaskVerification(student_id=student.id, task_id=task_id, proof_text=message.text.strip(), status="approved"))
            session.commit()
            await state.clear()
            await message.answer(f"✅ Правильно! Начислено {task.points} баллов.", reply_markup=main_menu_keyboard(user_id in ADMIN_IDS))
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
    await message.answer("📨 Доказательство отправлено на проверку.", reply_markup=main_menu_keyboard(user_id in ADMIN_IDS))


# ── Модерация ───────────────────────────────────────────────────────────────
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
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")]
                ])
            )

        buttons = []
        for v in pending:
            student = session.query(Student).get(v.student_id)
            task = session.query(Task).get(v.task_id)
            label = f"{student.full_name} — {task.title}"
            buttons.append([InlineKeyboardButton(text=label, callback_data=f"moderate_{v.id}")])

        buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")])

    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        f"📑 Заданий на проверке: {len(pending)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("moderate_"))
async def view_verification(callback: CallbackQuery):
    v_id = int(callback.data.split("_")[1])

    with Session() as session:
        v = session.query(TaskVerification).get(v_id)
        if not v:
            return await callback.answer("Не найдено")

        student = session.query(Student).get(v.student_id)
        task = session.query(Task).get(v.task_id)

        msg = (
            f"👤 Студент: {student.full_name}\n"
            f"📌 Задание: {task.title} (+{task.points} баллов)\n\n"
            f"📝 Доказательство:\n{v.proof_text or '(нет текста)'}"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Принять", callback_data=f"approve_{v_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{v_id}"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_moderation")],
        ])

    try:
        await callback.message.delete()
    except Exception:
        pass

    if v.proof_file:
        await callback.message.answer_photo(photo=v.proof_file, caption=msg, reply_markup=kb)
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

        student_tg = student.telegram_id
        task_title = task.title
        task_points = task.points

    await callback.answer("✅ Принято!")

    # Уведомляем студента
    if student_tg:
        try:
            await bot.send_message(student_tg, f"🎉 Твоё задание «{task_title}» принято! Начислено {task_points} баллов.")
        except Exception:
            pass

    # Обновляем список модерации
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

        student_tg = student.telegram_id
        task_title = task.title

    await callback.answer("❌ Отклонено")

    if student_tg:
        try:
            await bot.send_message(student_tg, f"😔 Твоё задание «{task_title}» отклонено модератором.")
        except Exception:
            pass

    await show_moderation(callback)


# ── Добавление задания ──────────────────────────────────────────────────────
@router.callback_query(F.data == "add_task")
async def add_task_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("⛔ У вас нет прав")
    await callback.message.answer("📌 Введите название задания:")
    await state.set_state(TaskState.AWAITING_TITLE)


@router.message(TaskState.AWAITING_TITLE)
async def get_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("📝 Введите описание:")
    await state.set_state(TaskState.AWAITING_DESCRIPTION)


@router.message(TaskState.AWAITING_DESCRIPTION)
async def get_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("💯 Введите количество баллов:")
    await state.set_state(TaskState.AWAITING_POINTS)


@router.message(TaskState.AWAITING_POINTS)
async def get_points(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❗ Введите целое число")
    await state.update_data(points=int(message.text.strip()))

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✏️ По ответу", callback_data="check_type:auto"),
        InlineKeyboardButton(text="📷 По доказательству", callback_data="check_type:manual"),
    ]])
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
    await _finish_task(message, state)


@router.message(TaskState.AWAITING_PROOF_TEXT)
async def get_proof_text(message: Message, state: FSMContext):
    await state.update_data(proof_text=message.text.strip())
    await _finish_task(message, state)


async def _finish_task(message: Message, state: FSMContext):
    data = await state.get_data()
    with Session() as session:
        session.add(Task(
            title=data["title"], description=data["description"],
            points=data["points"], verification_type=data["verification_type"],
            correct_answer=data.get("correct_answer"), proof_text=data.get("proof_text"),
        ))
        session.commit()
    await state.clear()
    await message.answer("✅ Задание добавлено.", reply_markup=main_menu_keyboard(message.from_user.id in ADMIN_IDS))
