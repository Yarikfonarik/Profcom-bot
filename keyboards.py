# keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📄 Задания",        callback_data="menu_tasks")],
        [InlineKeyboardButton(text="🛍 Магазин",        callback_data="menu_shop")],
        [InlineKeyboardButton(text="📊 Рейтинг",        callback_data="rating")],
        [InlineKeyboardButton(text="📥 Посещения",      callback_data="menu_events")],
        [InlineKeyboardButton(text="📈 Моя статистика", callback_data="my_stats")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="👨‍💼 Админ панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_button(callback_data: str = "menu_back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=callback_data)]
    ])
