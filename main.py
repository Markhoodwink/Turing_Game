import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.enums import ChatType

from config import BOT_TOKEN
from db import create_game, get_game, add_player, shuffle_and_assign_aliases, games
from kb import kb_join_game, kb_theme_choice, kb_vote
from states import GameStates
from ai_client import generate_theme, generate_ai_answer

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==========================================
# ГРУППОВЫЕ ХЕНДЛЕРЫ
# ==========================================

@dp.message(Command("start"), F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def cmd_start_group(message: types.Message):
    chat_id = message.chat.id
    if get_game(chat_id):
        await message.answer("Игра уже идет! Дождитесь окончания.")
        return
    
    create_game(chat_id, message.from_user.id)
    
    # Получаем username бота
    me = await bot.get_me() 
    
    await message.answer(
        f"🎭 <b>Человек или ИИ?</b>\n\n"
        f"Нажмите кнопку ниже, чтобы присоединиться.\n"
        f"⚠️ <b>Важно:</b> Чтобы бот мог писать вам ответы, напишите мне в ЛС: @{me.username}\n"
        f"После этого нажмите «Начать игру».",
        reply_markup=kb_join_game(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "join_game")
async def cb_join(call: types.CallbackQuery):
    game = get_game(call.message.chat.id)
    if not game or game["status"] != "lobby":
        await call.answer("Игра уже началась или закончилась!", show_alert=True)
        return
    
    alias = add_player(
        call.message.chat.id, 
        call.from_user.id, 
        call.from_user.full_name,
        call.from_user.username
    )
    
    # Получаем username бота
    me = await bot.get_me()
    
    await call.message.edit_text(
        f" <b>Человек или ИИ?</b>\n\n"
        f"Зарегистрирован как: <b>{alias}</b>\n"
        f"Игроков: {len(game['players'])}\n\n"
        f"️ Не забудьте написать боту в ЛС: @{me.username}!",
        reply_markup=kb_join_game(),
        parse_mode="HTML"
    )
    await call.answer()

@dp.callback_query(F.data == "start_game")
async def cb_start_game(call: types.CallbackQuery):
    game = get_game(call.message.chat.id)
    if not game: return
    
    # МЕНЯЕМ ЗДЕСЬ: было 3, стало 2
    if len(game["players"]) < 2:
        await call.answer("Нужно минимум 2 игрока!", show_alert=True)
        return
        
    if call.from_user.id != game["creator_id"]:
        await call.answer("Только создатель может начать игру!", show_alert=True)
        return

    game["status"] = "theme"
    await call.message.edit_text("🎯 Выберите, как будет формироваться тема:", reply_markup=kb_theme_choice())
    await call.answer()

@dp.callback_query(F.data == "theme_ai")
async def cb_theme_ai(call: types.CallbackQuery):
    game = get_game(call.message.chat.id)
    await call.message.edit_text("🤖 ИИ придумывает тему...")
    
    theme = await generate_theme()
    game["theme"] = theme
    
    await call.message.edit_text(f"🎯 <b>Тема:</b> {theme}\n\nСобираю ответы в ЛС...")
    await start_collecting(call.message.chat.id)

@dp.callback_query(F.data == "theme_custom")
async def cb_theme_custom(call: types.CallbackQuery, state: FSMContext):
    game = get_game(call.message.chat.id)
    if call.from_user.id != game["creator_id"]:
        await call.answer("Только создатель может выбрать тему!", show_alert=True)
        return
        
    await state.set_state(GameStates.waiting_custom_theme)
    logging.info(f" Установлено состояние waiting_custom_theme для чата {call.message.chat.id}")
    
    await call.message.edit_text("✍️ Напиши тему следующим сообщением в этот чат:")
    await call.answer()

@dp.message(GameStates.waiting_custom_theme, F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def process_custom_theme(message: types.Message, state: FSMContext):
    logging.info(f"📝 Получена кастомная тема: {message.text}")
    
    game = get_game(message.chat.id)
    if not game:
        logging.error("❌ Игра не найдена!")
        await message.answer("Ошибка: игра не найдена.")
        return
        
    game["theme"] = message.text
    await state.clear()
    
    logging.info(f"✅ Тема сохранена, начинаем сбор ответов")
    
    await message.answer(f" <b>Тема:</b> {message.text}\n\nСобираю ответы в ЛС...", parse_mode="HTML")
    await start_collecting(message.chat.id)

async def start_collecting(chat_id):
    """Отправляет запросы в ЛС и запускает таймер"""
    game = get_game(chat_id)
    game["status"] = "collecting"
    
    for uid, pdata in game["players"].items():
        try:
            await bot.send_message(
                uid, 
                f"🎯 <b>Тема:</b> {game['theme']}\n\n"
                f"Напиши свой ответ одним сообщением. У тебя <b>2 минуты</b>!",
                parse_mode="HTML"
            )
        except Exception as e:
            await bot.send_message(chat_id, f"⚠️ Не смог написать в ЛС игроку {pdata['name']}. Убедитесь, что он нажал /start в ЛС.")

    # Запускаем таймер на 2 минуты
    game["timer_task"] = asyncio.create_task(timer_task(chat_id, 120))

async def timer_task(chat_id, delay):
    await asyncio.sleep(delay)
    game = get_game(chat_id)
    if game and game["status"] == "collecting":
        await finish_collecting(chat_id)

# ==========================================
# ЛС ХЕНДЛЕРЫ (СБОР ОТВЕТОВ)
# ==========================================

@dp.message(F.chat.type == ChatType.PRIVATE)
async def ls_message_handler(message: types.Message):
    # Ищем игру, где есть этот юзер
    target_chat_id = None
    for chat_id, game in games.items(): # games импортируем из db
        if message.from_user.id in game.get("players", {}):
            if game["status"] == "collecting":
                target_chat_id = chat_id
                break
    
    if not target_chat_id:
        await message.answer("Сейчас нет активной игры. Дождитесь старта в группе.")
        return
        
    game = get_game(target_chat_id)
    player = game["players"][message.from_user.id]
    
    if player["answer"]:
        await message.answer("Ты уже отправил ответ! Жди результатов.")
        return
        
    player["answer"] = message.text
    await message.answer("✅ Ответ принят! Жди остальных.")
    
    # Проверяем, все ли ответили
    all_answered = all(p["answer"] is not None for p in game["players"].values())
    if all_answered:
        if game["timer_task"]:
            game["timer_task"].cancel()
        await finish_collecting(target_chat_id)

# ==========================================
# ФИНАЛ СБОРА И ГОЛОСОВАНИЕ
# ==========================================

async def finish_collecting(chat_id):
    game = get_game(chat_id)
    if game["status"] != "collecting": return
    game["status"] = "generating_ai"
    
    await bot.send_message(chat_id, "🤖 Все ответы собраны (или вышло время). ИИ пишет свой ответ...")
    
    # Собираем ответы людей для контекста
    human_answers = [p["answer"] for p in game["players"].values() if p["answer"]]
    
    # Генерируем ответ ИИ
    ai_answer = await generate_ai_answer(game["theme"], human_answers)
    game["ai_answer"] = ai_answer
    
    # Перемешиваем и назначаем алиасы
    final_answers = shuffle_and_assign_aliases(chat_id)
    
    # Формируем текст для голосования
    text = f"🎭 <b>Тема:</b> {game['theme']}\n\n"
    for alias, data in final_answers.items():
        text += f"<b>{alias}:</b> {data['text']}\n\n"
    text += "👇 <i>Кто из них ИИ? Голосуй!</i>"
    
    aliases = list(final_answers.keys())
    
    game["status"] = "voting"
    await bot.send_message(
        chat_id, 
        text, 
        reply_markup=kb_vote(aliases),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("vote_"))
async def cb_vote(call: types.CallbackQuery):
    game = get_game(call.message.chat.id)
    if not game or game["status"] != "voting":
        await call.answer("Голосование закрыто!", show_alert=True)
        return
        
    target_alias = call.data.split("_")[1]
    
    if call.from_user.id not in game["players"]:
        await call.answer("Ты не участвуешь в этой игре!", show_alert=True)
        return
        
    game["votes"][call.from_user.id] = target_alias
    await call.answer("Голос принят!")
    
    # Проверяем, все ли проголосовали
    if len(game["votes"]) == len(game["players"]):
        await reveal_results(call.message.chat.id)

# Можно добавить отдельную команду /reveal для досрочного вскрытия, если все устали ждать
@dp.message(Command("reveal"), F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def cmd_reveal(message: types.Message):
    game = get_game(message.chat.id)
    if game and game["status"] == "voting":
        await reveal_results(message.chat.id)

async def reveal_results(chat_id):
    game = get_game(chat_id)
    if game["status"] == "finished": return
    game["status"] = "finished"
    
    # Находим, какой алиас был у ИИ
    ai_alias = None
    for alias, data in game["final_answers"].items():
        if data["is_ai"]:
            ai_alias = alias
            break
            
    # Считаем голоса
    votes_count = {alias: 0 for alias in game["final_answers"].keys()}
    for voter_id, target in game["votes"].items():
        votes_count[target] += 1
        
    # Формируем результат
    result_text = f"🔪 <b>ВСКРЫТИЕ</b>\n\n"
    result_text += f"🤖 ИИ был под буквой <b>{ai_alias}</b>!\n"
    result_text += f"<i>Ответ ИИ:</i> {game['ai_answer']}\n\n"
    
    result_text += "📊 <b>Результаты голосования:</b>\n"
    for alias, count in votes_count.items():
        marker = "🤖" if alias == ai_alias else "👤"
        result_text += f"{marker} {alias}: {count} голос(ов)\n"
        
    await bot.send_message(chat_id, result_text, parse_mode="HTML")
    
    # Очищаем игру (с задержкой, чтобы успели прочитать)
    await asyncio.sleep(5)
    del games[chat_id]

# ==========================================
# ЗАПУСК
# ==========================================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n✅ Бот успешно остановлен!")