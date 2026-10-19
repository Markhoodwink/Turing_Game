import random
import string

# Хранилище активных игр: {chat_id: game_data}
games = {}

def create_game(chat_id, creator_id):
    games[chat_id] = {
        "creator_id": creator_id,
        "players": {},       # {user_id: {"name": "Имя", "alias": "A", "answer": None, "tg_username": "username"}}
        "theme": None,
        "ai_answer": None,
        "status": "lobby",   # lobby, theme, collecting, voting, finished
        "votes": {},         # {voter_id: target_alias}
        "timer_task": None
    }
    return games[chat_id]

def get_game(chat_id):
    return games.get(chat_id)

def add_player(chat_id, user_id, name, username):
    game = games[chat_id]
    if user_id not in game["players"]:
        # Генерируем уникальный алиас (A, B, C...)
        used_aliases = {p["alias"] for p in game["players"].values()}
        available = [l for l in string.ascii_uppercase if l not in used_aliases]
        alias = random.choice(available) if available else "?"
        
        game["players"][user_id] = {
            "name": name,
            "alias": alias,
            "answer": None,
            "tg_username": username
        }
        return alias
    return game["players"][user_id]["alias"]

import random
import string

def shuffle_and_assign_aliases(chat_id):
    """Перемешивает ответы и назначает финальные алиасы для голосования"""
    game = games[chat_id]
    all_answers = []
    
    # Собираем ответы людей
    for uid, pdata in game["players"].items():
        if pdata["answer"]:
            all_answers.append({"text": pdata["answer"], "is_ai": False, "owner_id": uid})
            
    # Добавляем ответ ИИ
    all_answers.append({"text": game["ai_answer"], "is_ai": True, "owner_id": None})
    
    # Перемешиваем
    random.shuffle(all_answers)
    
    # Назначаем новые алиасы (A, B, C...)
    final_aliases = {}
    for i, ans in enumerate(all_answers):
        alias = string.ascii_uppercase[i]
        ans["alias"] = alias
        final_aliases[alias] = ans
        
    # Сохраняем в игру и возвращаем
    game["final_answers"] = final_aliases
    return final_aliases