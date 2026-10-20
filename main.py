import asyncio
import logging
import json
import os
from aiogram.exceptions import TelegramForbiddenError
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.enums import ChatType

from config import BOT_TOKEN, ADMIN_ID
from db import create_game, get_game, add_player, shuffle_and_assign_aliases, games, update_group_stats, get_group_stats, reset_group_stats, update_ai_stats, get_ai_stats
from kb import kb_join_game, kb_theme_choice, kb_vote, kb_play_again, kb_reset_stats
from states import GameStates
from ai_client import generate_theme, generate_ai_answer

# Твой Telegram ID (для защиты команды рассылки)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "users.json")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==========================================
# ГРУППОВЫЕ ХЕНДЛЕРЫ
# ==========================================

# === Работа с файлом пользователей ===

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    # Проверяем, что команду пишет админ
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У тебя нет прав для этой команды.")
        return
    
    # Проверяем, что команда в ЛС (не в группе)
    if message.chat.type != ChatType.PRIVATE:
        await message.answer("Эта команда работает только в личных сообщениях с ботом.")
        return
    
    # Получаем текст для рассылки
    text_to_send = message.text.replace("/broadcast", "").strip()
    
    if not text_to_send:
        await message.answer("Используй: /broadcast Текст сообщения")
        return
    
    # Загружаем всех пользователей
    users = load_users()
    sent_count = 0
    blocked_count = 0
    
    await message.answer(f"📢 Начинаю рассылку {len(users)} пользователям...")
    
    # Отправляем сообщение каждому
    for user_id in users:
        try:
            await bot.send_message(user_id, text_to_send)
            sent_count += 1
            # Небольшая задержка, чтобы не превысить лимиты Telegram
            await asyncio.sleep(0.05)
        except TelegramForbiddenError:
            # Пользователь заблокировал бота
            blocked_count += 1
            print(f"Пользователь {user_id} заблокировал бота")
        except Exception as e:
            print(f"Ошибка при отправке {user_id}: {e}")
    
    await message.answer(f"✅ Рассылка завершена!\n📤 Отправлено: {sent_count}\n🚫 Заблокировали: {blocked_count}")

def load_users():
    """Загружает список пользователей из файла"""
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_user(user_id: int):
    """Добавляет пользователя в файл (если его там еще нет)"""
    users = load_users()
    if user_id not in users:
        users.append(user_id)
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)

@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    """Показать количество зарегистрированных пользователей"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У тебя нет прав для этой команды.")
        return
    
    users = load_users()
    await message.answer(f"👥 Всего пользователей в базе: {len(users)}")

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

async def vote_timer_task(chat_id, delay):
    await asyncio.sleep(delay)
    game = get_game(chat_id)
    # Если игра все еще в статусе голосования — время вышло
    if game and game["status"] == "voting":
        await bot.send_message(chat_id, "⏱️ <b>Время на голосование вышло!</b> Вскрываем карты...", parse_mode="HTML")
        await reveal_results(chat_id)

# ==========================================
# ЛС ХЕНДЛЕРЫ (СБОР ОТВЕТОВ)
# ==========================================

@dp.message(F.chat.type == ChatType.PRIVATE)
async def ls_message_handler(message: types.Message, state: FSMContext):
    # 1. Сохраняем пользователя при любом сообщении в ЛС
    save_user(message.from_user.id)
    
    # 2. Проверяем, не ждем ли мы тему от создателя
    current_state = await state.get_state()
    if current_state == GameStates.waiting_custom_theme:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        
        if not chat_id:
            await message.answer("⚠️ Ошибка: игра не найдена. Начни заново.")
            return
        
        game = get_game(chat_id)
        if not game:
            await message.answer("⚠️ Игра не найдена!")
            return
        
        game["theme"] = message.text
        await state.clear()
        
        await message.answer("✅ Тема принята! Передаю в группу...")
        
        await bot.send_message(
            chat_id,
            f" <b>Тема:</b> {message.text}\n\nСобираю ответы в ЛС...",
            parse_mode="HTML"
        )
        
        await start_collecting(chat_id)
        return
    
    # 3. Обычная логика сбора ответов (переименовали game -> g в цикле)
    target_chat_id = None
    for chat_id, g in games.items():  # <-- переименовали game в g
        if message.from_user.id in g.get("players", {}):
            if g["status"] == "collecting":
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
    game["vote_timer_task"] = asyncio.create_task(vote_timer_task(chat_id, 90))

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
        # Останавливаем таймер, так как все уже проголосовали
        if game.get("vote_timer_task"):
            game["vote_timer_task"].cancel()
        await reveal_results(call.message.chat.id)

# Можно добавить отдельную команду /reveal для досрочного вскрытия, если все устали ждать
@dp.message(Command("reveal"), F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def cmd_reveal(message: types.Message):
    game = get_game(message.chat.id)
    if game and game["status"] == "voting":
        await reveal_results(message.chat.id)

async def reveal_results(chat_id):
    game = get_game(chat_id)
    if not game or game["status"] == "finished": 
        return
        
    # Подстраховка: отменяем таймер голосования
    if game.get("vote_timer_task"):
        game["vote_timer_task"].cancel()
        
    game["status"] = "finished"
    
    # Находим алиас ИИ
    ai_alias = None
    for alias, data in game["final_answers"].items():
        if data["is_ai"]:
            ai_alias = alias
            break
    
    # Считаем голоса
    votes_count = {alias: 0 for alias in game["final_answers"].keys()}
    for voter_id, target in game["votes"].items():
        votes_count[target] += 1
    
    # === ПОДСЧЕТ ОЧКОВ ===
    player_scores = {}  # {user_id: {"score": 0, "username": "...", "votes_received": 0}}
    
    # Инициализируем очки для всех игроков
    for user_id, player_data in game["players"].items():
        username = player_data.get("tg_username") or player_data["name"]
        player_scores[user_id] = {
            "score": 0,
            "username": username,
            "votes_received": 0,
            "voted_for": game["votes"].get(user_id)
        }
    
    # Сопоставляем алиасы с игроками и считаем очки
    alias_to_user = {}
    for alias, data in game["final_answers"].items():
        if not data["is_ai"]:
            alias_to_user[alias] = data["owner_id"]
    
    # 1. Очки за угадывание ИИ (+1 если угадал, +0 если нет)
    for user_id, score_data in player_scores.items():
        voted_alias = score_data["voted_for"]
        if voted_alias == ai_alias:
            score_data["score"] += 1
    
    # 2. Очки за то, что на тебя подумали как на ИИ (+3 если больше всего голосов)
    max_votes = max(votes_count.values()) if votes_count else 0
    for alias, count in votes_count.items():
        if count == max_votes and count > 0:
            user_id = alias_to_user.get(alias)
            if user_id and user_id in player_scores:
                player_scores[user_id]["score"] += 3
                player_scores[user_id]["votes_received"] = count
    
    # 3. Очки для ИИ (+2 если большинство голосов НЕ за неё)
    ai_votes = votes_count.get(ai_alias, 0)
    total_votes = len(game["votes"])
    ai_score = 0
    if total_votes > 0 and ai_votes < total_votes / 2:
        ai_score = 2

    # === СОХРАНЕНИЕ СТАТИСТИКИ ===
    update_group_stats(chat_id, player_scores)
    
    # Сохраняем очки ИИ
    if ai_score > 0:
        update_ai_stats(chat_id, ai_score)
    
    # === ФОРМИРОВАНИЕ СООБЩЕНИЯ ===
    result_text = f"🔪 <b>ВСКРЫТИЕ</b>\n\n"
    result_text += f"🤖 ИИ был под буквой <b>{ai_alias}</b>!\n"
    result_text += f"<i>Ответ ИИ:</i> {game['ai_answer']}\n\n"
    
    result_text += f"📊 <b>Результаты голосования:</b>\n"
    for alias, count in votes_count.items():
        user_id = alias_to_user.get(alias)
        if user_id:
            username = player_scores[user_id]["username"]
            marker = "🤖" if alias == ai_alias else "👤"
            result_text += f"{marker} <b>{alias}</b> (@{username}): {count} голос(ов)\n"
        else:
            marker = "🤖" if alias == ai_alias else "👤"
            result_text += f"{marker} <b>{alias}</b>: {count} голос(ов)\n"
    
    result_text += f"\n🏆 <b>Очки за раунд:</b>\n"
    for user_id, score_data in sorted(player_scores.items(), key=lambda x: x[1]["score"], reverse=True):
        result_text += f"👤 @{score_data['username']}: <b>{score_data['score']}</b> очк.\n"
    
    result_text += f"\n🤖 <b>ИИ заработала: {ai_score} очк.</b>\n"
    if ai_score > 0:
        result_text += "<i>(Большинство не заподозрило машину!)</i>\n"
    
    # Отправляем сообщение с кнопкой "Играть снова"
    await bot.send_message(
        chat_id, 
        result_text, 
        reply_markup=kb_play_again(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "play_again")
async def cb_play_again(call: types.CallbackQuery):
    chat_id = call.message.chat.id
    
    # Создаем новую игру поверх старой (это очистит старые ответы и голоса)
    create_game(chat_id, call.from_user.id)
    
    me = await bot.get_me()
    
    # Отправляем то же сообщение, что и при /start
    await call.message.edit_text(
        f"🎭 <b>Новая игра «Человек или ИИ»!</b>\n\n"
        f"Нажмите кнопку ниже, чтобы присоединиться.\n"
        f"⚠️ <b>Важно:</b> Чтобы бот мог писать вам ответы, напишите мне в ЛС: @{me.username}\n"
        f"После этого нажмите «Начать игру».",
        reply_markup=kb_join_game(),
        parse_mode="HTML"
    )
    await call.answer()

@dp.message(Command("stats"), F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def cmd_stats(message: types.Message):
    """Показать таблицу лидеров группы (включая ИИ)"""
    chat_id = message.chat.id
    top_players = get_group_stats(chat_id, top_n=10)
    ai_score = get_ai_stats(chat_id)
    
    if not top_players and ai_score == 0:
        await message.answer("📊 Статистика пуста. Сыграйте хотя бы одну игру!")
        return
    
    text = "🏆 <b>Таблица лидеров:</b>\n\n"
    
    # Собираем всех участников (игроки + ИИ) для сортировки
    all_participants = []
    
    # Добавляем обычных игроков, ПРОПУСКАЯ ai_bot (чтобы не дублировать)
    for user_id, data in top_players:
        if user_id != "ai_bot":  # <-- ЭТО КЛЮЧЕВОЕ ИЗМЕНЕНИЕ
            all_participants.append({"username": data["username"], "score": data["total_score"], "is_ai": False})
    
    # Добавляем ИИ отдельно
    if ai_score > 0:
        all_participants.append({"username": "ИИ", "score": ai_score, "is_ai": True})
    
    # Сортируем по очкам
    all_participants.sort(key=lambda x: x["score"], reverse=True)
    
    # Формируем таблицу
    for i, participant in enumerate(all_participants, 1):
        if participant["is_ai"]:
            medal = "🤖"
            text += f"{medal} <b>{participant['username']}</b>: {participant['score']} очк.\n"
        else:
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            text += f"{medal} <b>@{participant['username']}</b>: {participant['score']} очк.\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("reset"), F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def cmd_reset(message: types.Message):
    """Сбросить статистику группы (только для создателя последней игры)"""
    chat_id = message.chat.id
    game = get_game(chat_id)
    
    # Проверяем, что есть активная или завершённая игра
    if not game:
        await message.answer("⚠️ Нет активной игры в этой группе.")
        return
    
    # Только создатель последней игры может сбросить счёт
    if message.from_user.id != game["creator_id"]:
        await message.answer(" Только создатель последней игры может сбросить счёт!")
        return
    
    await message.answer(
        "⚠️ <b>Вы уверены, что хотите сбросить счёт всей группы?</b>\n"
        "Это действие нельзя отменить.",
        reply_markup=kb_reset_stats(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "reset_stats")
async def cb_reset_stats(call: types.CallbackQuery):
    """Подтверждение сброса статистики"""
    chat_id = call.message.chat.id
    game = get_game(chat_id)
    
    if not game or call.from_user.id != game["creator_id"]:
        await call.answer(" Только создатель может подтвердить сброс!", show_alert=True)
        return
    
    reset_group_stats(chat_id)
    await call.message.edit_text("✅ <b>Статистика группы сброшена!</b> Все начинают с нуля.", parse_mode="HTML")
    await call.answer()

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