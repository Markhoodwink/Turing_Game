from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def kb_join_game():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋‍♂️ Участвовать", callback_data="join_game")],
        # МЕНЯЕМ ЗДЕСЬ
        [InlineKeyboardButton(text="🚀 Начать игру (мин. 2 чел.)", callback_data="start_game")]
    ])

def kb_theme_choice():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Пусть ИИ придумает", callback_data="theme_ai")],
        [InlineKeyboardButton(text="✍️ Напишу сам (ответь в чат)", callback_data="theme_custom")]
    ])

def kb_vote(aliases):
    """Клавиатура для голосования"""
    buttons = []
    row = []
    for alias in aliases:
        row.append(InlineKeyboardButton(text=alias, callback_data=f"vote_{alias}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_play_again():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Играть снова", callback_data="play_again")]
    ])

def kb_reset_stats():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Сбросить счёт группы", callback_data="reset_stats")]
    ])