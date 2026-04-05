# handlers/navigation.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import text

from config import ADMIN_IDS
from keyboards import main_menu_keyboard
from database import Session

router = Router()

def is_mod(user_id): return user_id in ADMIN_IDS

async def send_main_menu(target, is_admin: bool):
    kb = main_menu_keyboard(is_admin)
    if isinstance(target, Message):
        await target.answer("🏠 Главное меню:", reply_markup=kb)
    else:
        try: await target.message.delete()
        except Exception: pass
        await target.message.answer("🏠 Главное меню:", reply_markup=kb)


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    await send_main_menu(message, is_mod(message.from_user.id))


@router.callback_query(F.data == "menu_back")
async def go_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await send_main_menu(callback, is_mod(callback.from_user.id))


@router.callback_query(F.data == "menu_main")
async def menu_main(callback: CallbackQuery, state: FSMContext):
    await go_back(callback, state)


@router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if not is_mod(callback.from_user.id):
        return await callback.answer("⛔ Нет прав", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        "👨‍💼 Админ панель:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Студенты",               callback_data="students")],
            [InlineKeyboardButton(text="📊 Статистика системы",     callback_data="stats")],
            [InlineKeyboardButton(text="📤 Мероприятия",            callback_data="menu_events")],
            [InlineKeyboardButton(text="📑 Модерация заданий",      callback_data="menu_moderation")],
            [InlineKeyboardButton(text="📝 Статистика заданий",     callback_data="task_stats_menu")],
            [InlineKeyboardButton(text="🛍 Статистика магазина",    callback_data="shop_stats_menu")],
            [InlineKeyboardButton(text="🔁 Сбросить данные",        callback_data="reset_menu")],
            [InlineKeyboardButton(text="⬅️ Главное меню",           callback_data="menu_back")],
        ])
    )


@router.callback_query(F.data == "reset_menu")
async def reset_menu(callback: CallbackQuery):
    if not is_mod(callback.from_user.id):
        return await callback.answer("⛔ Нет прав", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass
    await callback.message.answer(
        "🔁 Сбросить данные:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Сбросить все баллы",        callback_data="reset_all_balances")],
            [InlineKeyboardButton(text="📝 Сбросить все задания",      callback_data="reset_all_tasks")],
            [InlineKeyboardButton(text="🛍 Сбросить весь магазин",     callback_data="reset_all_shop")],
            [InlineKeyboardButton(text="🎪 Сбросить мероприятия",      callback_data="reset_all_events")],
            [InlineKeyboardButton(text="⬅️ Назад",                    callback_data="admin_panel")],
        ])
    )


def _confirm_kb(yes_cb: str, no_cb: str = "reset_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, сбросить", callback_data=yes_cb),
        InlineKeyboardButton(text="❌ Отмена", callback_data=no_cb),
    ]])


@router.callback_query(F.data == "reset_all_balances")
async def confirm_reset_balances(callback: CallbackQuery):
    await callback.message.answer(
        "⚠️ Сбросить баллы ВСЕХ студентов?\nОсновной баланс + баллы мероприятий.",
        reply_markup=_confirm_kb("do_reset_balances")
    )


@router.callback_query(F.data == "do_reset_balances")
async def do_reset_balances(callback: CallbackQuery):
    with Session() as session:
        session.execute(text("UPDATE students SET balance = 0"))
        session.execute(text("UPDATE event_participants SET event_balance = 0"))
        session.commit()
    await callback.answer("✅ Все баллы сброшены!", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass
    await admin_panel(callback)


@router.callback_query(F.data == "reset_all_tasks")
async def confirm_reset_tasks(callback: CallbackQuery):
    await callback.message.answer(
        "⚠️ Удалить ВСЕ задания и результаты?",
        reply_markup=_confirm_kb("do_reset_tasks")
    )


@router.callback_query(F.data == "do_reset_tasks")
async def do_reset_tasks(callback: CallbackQuery):
    with Session() as session:
        session.execute(text("DELETE FROM task_verifications"))
        session.execute(text("UPDATE tasks SET is_deleted = TRUE"))
        session.commit()
    await callback.answer("✅ Задания сброшены!", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass
    await admin_panel(callback)


@router.callback_query(F.data == "reset_all_shop")
async def confirm_reset_shop(callback: CallbackQuery):
    await callback.message.answer(
        "⚠️ Удалить ВСЕ товары и покупки?",
        reply_markup=_confirm_kb("do_reset_shop")
    )


@router.callback_query(F.data == "do_reset_shop")
async def do_reset_shop(callback: CallbackQuery):
    with Session() as session:
        session.execute(text("DELETE FROM purchases"))
        session.execute(text("UPDATE merchandise SET is_deleted = TRUE, stock = 0"))
        session.commit()
    await callback.answer("✅ Магазин сброшен!", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass
    await admin_panel(callback)


@router.callback_query(F.data == "reset_all_events")
async def confirm_reset_events(callback: CallbackQuery):
    await callback.message.answer(
        "⚠️ Закрыть ВСЕ мероприятия и сбросить баллы участников?",
        reply_markup=_confirm_kb("do_reset_events")
    )


@router.callback_query(F.data == "do_reset_events")
async def do_reset_events(callback: CallbackQuery):
    with Session() as session:
        session.execute(text("UPDATE events SET status = 'closed' WHERE status = 'active'"))
        session.execute(text("UPDATE event_participants SET event_balance = 0"))
        session.commit()
    await callback.answer("✅ Мероприятия сброшены!", show_alert=True)
    try: await callback.message.delete()
    except Exception: pass
    await admin_panel(callback)
