import os
import sys
from datetime import datetime
from openai import OpenAI

sys.path.append("/root/coalbot")
from config import OPENAI_API_KEY

DATA_DIR = "/root/coalbot/data_runs"
client = OpenAI(api_key=OPENAI_API_KEY)

def collect_current_month():
    now = datetime.now()
    items = []

    for root, dirs, files in os.walk(DATA_DIR):
        if "final_summary_ru.txt" not in files:
            continue

        path = os.path.join(root, "final_summary_ru.txt")
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
        except Exception:
            continue

        if mtime.year != now.year or mtime.month != now.month:
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

def build_monthly_summary():
    items = collect_current_month()

    if not items:
        return "📌 Месячная сводка по углю\n\nНет данных за текущий месяц."

    joined = "\n\n".join([f"[{os.path.basename(os.path.dirname(p))}]\n{txt}" for _, p, txt in items])

    prompt = f"""
Ты готовишь МЕСЯЧНУЮ СВОДКУ по угольному рынку на русском языке.

Ниже даны ежедневные сводки за текущий месяц.
Не сканируй сайты заново. Работай только по этому материалу.

Сделай обзор в таком формате:

📌 Месячная сводка по углю
Период обзора:
— ...

Главные события месяца:
1) ...
2) ...
3) ...
4) ...
5) ...

Ключевые тренды месяца:
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
- нормальный плотный русский язык
- максимум 5 главных событий месяца
- объединяй повторяющиеся темы
- отдельно оцени Китай и внешний рынок, если это реально влияло

Материал:
{joined}
"""

    resp = client.responses.create(
        model="gpt-5.4",
        input=prompt
    )
    return resp.output_text.strip()

if __name__ == "__main__":
    print(build_monthly_summary())
