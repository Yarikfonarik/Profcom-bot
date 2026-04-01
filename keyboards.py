# keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove

# Скрывает нижнее меню (Reply-клавиатуру)
REMOVE_KEYBOARD = ReplyKeyboardRemove()


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📄 Задания",         callback_data="menu_tasks")],
        [InlineKeyboardButton(text="🛍 Магазин",         callback_data="menu_shop")],
        [InlineKeyboardButton(text="📥 Мероприятия",     callback_data="menu_events")],
        [InlineKeyboardButton(text="👤 Профиль",         callback_data="my_profile")],
        [InlineKeyboardButton(text="🆘 Поддержка",       callback_data="support")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="👨‍💼 Админ панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_button(callback_data: str = "menu_back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=callback_data)]
    ])
