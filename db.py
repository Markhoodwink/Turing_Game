import random
import string
import json
import os

# ==========================================
# ПУТИ К ФАЙЛАМ (Абсолютные пути для хостинга)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATS_FILE = os.path.join(BASE_DIR, "stats.json")

# ==========================================
# ХРАНИЛИЩЕ АКТИВНЫХ ИГР (в оперативной памяти)
# ==========================================
games = {}
# ... дальше идет твой код ...

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

# ==========================================
# СТАТИСТИКА (сохраняется в файл stats.json)
# ==========================================

STATS_FILE = "stats.json"

def load_stats():
    """Загружает статистику из файла"""
    if not os.path.exists(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_stats(data):
    """Сохраняет статистику в файл"""
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Глобальная переменная, которую мы будем обновлять
all_stats = load_stats()

def update_group_stats(chat_id, player_scores):
    """Добавляет очки и сразу сохраняет в файл"""
    global all_stats
    
    if chat_id not in all_stats:
        all_stats[chat_id] = {}
    
    for user_id, score_data in player_scores.items():
        if user_id not in all_stats[chat_id]:
            all_stats[chat_id][user_id] = {"username": score_data["username"], "total_score": 0}
        
        all_stats[chat_id][user_id]["total_score"] += score_data["score"]
        # Обновляем username, если он изменился
        all_stats[chat_id][user_id]["username"] = score_data["username"]
        
    # Сохраняем изменения на диск после каждого раунда
    save_stats(all_stats)

def get_group_stats(chat_id, top_n=10):
    """Возвращает топ-N игроков группы"""
    if chat_id not in all_stats:
        return []
    
    sorted_players = sorted(
        all_stats[chat_id].items(),
        key=lambda x: x[1]["total_score"],
        reverse=True
    )
    return sorted_players[:top_n]

def reset_group_stats(chat_id):
    """Сбрасывает статистику группы (игроков и ИИ) и сохраняет"""
    global all_stats
    if chat_id in all_stats:
        del all_stats[chat_id]
        save_stats(all_stats)

# ==========================================
# СТАТИСТИКА ИИ (сохраняется в stats.json)
# ==========================================

def update_ai_stats(chat_id, ai_score):
    """Добавляет очки ИИ к его общему счёту в группе"""
    global all_stats
    
    # Используем специальный ключ "ai_bot" для хранения очков ИИ
    if chat_id not in all_stats:
        all_stats[chat_id] = {}
    
    if "ai_bot" not in all_stats[chat_id]:
        all_stats[chat_id]["ai_bot"] = {"username": "ИИ", "total_score": 0}
    
    all_stats[chat_id]["ai_bot"]["total_score"] += ai_score
    save_stats(all_stats)

def get_ai_stats(chat_id):
    """Возвращает очки ИИ в группе"""
    if chat_id not in all_stats:
        return 0
    return all_stats[chat_id].get("ai_bot", {}).get("total_score", 0)