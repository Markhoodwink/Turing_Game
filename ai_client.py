import asyncio
from groq import Groq
from config import GROQ_API_KEY

client = Groq(api_key=GROQ_API_KEY)

def _sync_request(prompt, system_prompt):
    """Синхронный вызов Groq, который мы будем оборачивать в asyncio"""
    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=200
    )
    return response.choices[0].message.content.strip()

async def generate_theme():
    """ИИ генерирует тему"""
    prompt = ("Придумай короткий, жизненный и немного провокационный вопрос для игры 'Человек или ИИ'. "
              "Например: 'Почему ты опоздал?' или 'Что бесит в людях?'. "
              "Верни ТОЛЬКО текст вопроса, без кавычек и пояснений.")
    return await asyncio.to_thread(_sync_request, prompt, "Ты креативный ведущий игры.")

async def generate_ai_answer(theme, human_answers):
    """ИИ генерирует свой ответ, подстраиваясь под людей"""
    answers_text = "\n".join([f"- {ans}" for ans in human_answers])
    prompt = f"""Ты участвуешь в игре. Люди ответили на вопрос: '{theme}'. 
Ответы людей:
{answers_text}

Твоя задача: Напиши ОДИН ответ на этот вопрос от лица обычного человека. 
Подстройся под стиль, длину и тон ответов людей. Если люди пишут коротко - пиши коротко. 
Не пиши как ИИ (никаких списков, 'в целом', 'как модель', идеальной пунктуации). 
Пиши живо, можно с опечатками, без точки в конце.
Верни ТОЛЬКО текст ответа."""
    return await asyncio.to_thread(_sync_request, prompt, "Ты обычный человек в чате, участвуешь в игре.")