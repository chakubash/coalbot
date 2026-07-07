import os
import re
import sys
from datetime import datetime, timedelta
from openai import OpenAI

sys.path.append("/root/coalbot")
from config import OPENAI_API_KEY

DATA_DIR = "/root/coalbot/data_runs"
client = OpenAI(api_key=OPENAI_API_KEY)

def collect_last_7_days():
    cutoff = datetime.now() - timedelta(days=7)
    items = []

    for root, dirs, files in os.walk(DATA_DIR):
        if "final_summary_ru.txt" not in files:
            continue

        path = os.path.join(root, "final_summary_ru.txt")
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
        except Exception:
            continue

        if mtime < cutoff:
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                txt = f.read().strip()
            if txt:
                items.append((mtime, path, txt))
        except Exception:
            pass

    items.sort(key=lambda x: x[0])
    return items

def build_weekly_summary():
    items = collect_last_7_days()

    if not items:
        return "📌 Недельная сводка по углю\n\nНет данных за последние 7 дней."

    joined = "\n\n".join([f"[{os.path.basename(os.path.dirname(p))}]\n{txt}" for _, p, txt in items])

    prompt = f"""
Ты готовишь НЕДЕЛЬНУЮ СВОДКУ по угольному рынку на русском языке.

Ниже даны ежедневные сводки за последние 7 дней.
Не сканируй сайты заново. Работай только по этому материалу.

Сделай обзор в таком формате:

📌 Недельная сводка по углю
Период обзора:
— ...

Главные события недели:
1) ...
2) ...
3) ...
4) ...
5) ...

Что это значит:
— ...
— ...
— ...

Общая картина рынка:
Коксующийся уголь:
— ...
Кокс:
— ...
Энергетический уголь:
— ...

Вывод:
— ...
— ...
— ...

Требования:
- без воды
- плотный русский язык
- максимум 5 главных событий недели
- если тема повторялась несколько дней, объедини её в один вывод
- акцент на Китай, но внешний рынок тоже учитывай, если он реально влиял

Материал:
{joined}
"""

    resp = client.responses.create(
        model="gpt-5.4",
        input=prompt
    )
    return resp.output_text.strip()

if __name__ == "__main__":
    print(build_weekly_summary())
