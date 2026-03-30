# keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Главное меню бота. Единственный источник истины для callback_data кнопок."""
    buttons = [
        [InlineKeyboardButton(text="📄 Задания",       callback_data="menu_tasks")],
        [InlineKeyboardButton(text="🛍 Магазин",       callback_data="menu_shop")],
        [InlineKeyboardButton(text="📊 Рейтинг",       callback_data="rating")],
        [InlineKeyboardButton(text="📥 Посещения",     callback_data="menu_events")],
        [InlineKeyboardButton(text="📈 Моя статистика", callback_data="my_stats")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="👥 Студенты",            callback_data="students")])
        buttons.append([InlineKeyboardButton(text="📊 Статистика системы",  callback_data="stats")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_button(callback_data: str = "menu_back") -> InlineKeyboardMarkup:
    """Универсальная кнопка «Назад»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=callback_data)]
    ])
