from aiogram.fsm.state import State, StatesGroup

class GameStates(StatesGroup):
    waiting_custom_theme = State()  # Ждем, пока создатель напишет тему в чат
    waiting_ls_answer = State()     # Ждем ответ от игрока в ЛС