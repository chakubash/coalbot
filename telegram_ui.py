def get_ai_button_text(ai_enabled):
    return '❌ Выключить AI' if ai_enabled else '🤖 Включить AI'

import asyncio
import os
import json
import requests
import subprocess
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from openai import OpenAI

from config import TELEGRAM_BOT_TOKEN, OPENAI_API_KEY
from storage import add_subscriber, load_subscribers
from scheduler import build_manual_summary, get_recent_manual_summary, get_last_scheduled_report
from reports.weekly_report import build_weekly_summary
from reports.monthly_report import build_monthly_summary

client = OpenAI(api_key=OPENAI_API_KEY)

AI_MODE_FILE = "/root/coalbot/reports/ai_mode_chats.json"
DATA_DIR = "/root/coalbot/data_runs"


def load_ai_mode_chats():
    if not os.path.exists(AI_MODE_FILE):
        return set()
    try:
        with open(AI_MODE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(str(x) for x in data)
    except Exception:
        return set()


def save_ai_mode_chats(chats):
    os.makedirs(os.path.dirname(AI_MODE_FILE), exist_ok=True)
    with open(AI_MODE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(chats)), f, ensure_ascii=False, indent=2)


AI_MODE_CHATS = load_ai_mode_chats()

MANUAL_RECENT_SUMMARY_TEXT = "Сводка за последние 45 минут уже была сформирована, поэтому отправляю последнюю готовую версию."


def split_long_text(text: str, chunk_size: int = 3800):
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > chunk_size:
            if current:
                chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def send_telegram_message(chat_id: str, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": True
        },
        timeout=60
    )
    resp.raise_for_status()
    return resp.json()


def broadcast_pair(ru_text: str, zh_text: str):
    subs = load_subscribers()
    sent_chat_ids = []
    errors = {}

    for chat_id in subs.get("chat_ids", []):
        try:
            for chunk in split_long_text(ru_text):
                send_telegram_message(chat_id, chunk)
            if zh_text:
                for chunk in split_long_text(zh_text):
                    send_telegram_message(chat_id, chunk)
            sent_chat_ids.append(str(chat_id))
        except Exception as e:
            errors[str(chat_id)] = repr(e)

    return {
        "sent_chat_ids": sent_chat_ids,
        "errors": errors,
        "ok": len(errors) == 0 and len(sent_chat_ids) > 0,
    }


def build_inline_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Оперативная сводка", callback_data="manual_summary")],
        [InlineKeyboardButton("📅 Недельная сводка", callback_data="weekly_now")],
        [InlineKeyboardButton("📆 Месячная сводка", callback_data="monthly_now")],
        [InlineKeyboardButton("🕛 Последняя сводка 12:00", callback_data="last_midday")],
        [InlineKeyboardButton("🌙 Последняя сводка 20:00", callback_data="last_evening")],
        [InlineKeyboardButton("🛰 Статус системы", callback_data="status_now")],
        [InlineKeyboardButton("🛠 Debug", callback_data="debug_now")],
    ])


def build_reply_keyboard(ai_enabled: bool):
    ai_text = "❌ Выключить AI" if ai_enabled else "🤖 Включить AI"
    return ReplyKeyboardMarkup(
        [
            ["⬛️ Обзор рынка угля"],
            [ai_text]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


async def safe_send_pair(chat_id: str, ru_text: str, zh_text: str, bot):
    for chunk in split_long_text(ru_text):
        await bot.send_message(chat_id=chat_id, text=chunk, disable_web_page_preview=True)
        await asyncio.sleep(0.4)
    if zh_text:
        for chunk in split_long_text(zh_text):
            await bot.send_message(chat_id=chat_id, text=chunk, disable_web_page_preview=True)
            await asyncio.sleep(0.4)


def _latest_summary_text():
    if not os.path.exists(DATA_DIR):
        return "Нет данных по сводкам."

    folders = []
    for x in os.listdir(DATA_DIR):
        p = os.path.join(DATA_DIR, x)
        if os.path.isdir(p):
            folders.append(p)

    if not folders:
        return "Нет данных по сводкам."

    folders.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    for folder in folders:
        ru = os.path.join(folder, "final_summary_ru.txt")
        if os.path.exists(ru):
            try:
                with open(ru, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                if txt:
                    return txt
            except Exception:
                pass

    return "Не удалось найти готовую сводку."


def _count_summaries(days=None, current_month=False):
    if not os.path.exists(DATA_DIR):
        return 0

    now = datetime.now()
    count = 0

    for root, dirs, files in os.walk(DATA_DIR):
        if "final_summary_ru.txt" not in files:
            continue

        path = os.path.join(root, "final_summary_ru.txt")
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
        except Exception:
            continue

        if current_month:
            if mtime.year == now.year and mtime.month == now.month:
                count += 1
        elif days is not None:
            delta = now - mtime
            if delta.days <= days:
                count += 1
        else:
            count += 1

    return count


def _process_alive(pattern: str) -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def _latest_run_folder():
    if not os.path.exists(DATA_DIR):
        return None

    folders = []
    for x in os.listdir(DATA_DIR):
        p = os.path.join(DATA_DIR, x)
        if os.path.isdir(p):
            folders.append(p)

    if not folders:
        return None

    folders.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    return folders[0]


def _count_jsonl_lines(path: str) -> int:
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _build_debug_text():
    latest = _latest_run_folder()
    if latest:
        latest_name = os.path.basename(latest)
        raw_n = _count_jsonl_lines(os.path.join(latest, "raw_candidates.jsonl"))
        gated_n = _count_jsonl_lines(os.path.join(latest, "gated_candidates.jsonl"))
        norm_n = _count_jsonl_lines(os.path.join(latest, "normalized_articles.jsonl"))
        analyzed_n = _count_jsonl_lines(os.path.join(latest, "analyzed_articles.jsonl"))
    else:
        latest_name = "нет"
        raw_n = gated_n = norm_n = analyzed_n = 0

    return (
        "⬛ Debug\n\n"
        f"▪️ Последний запуск: {latest_name}\n"
        f"▪️ Raw candidates: {raw_n}\n"
        f"▪️ Gated candidates: {gated_n}\n"
        f"▪️ Normalized articles: {norm_n}\n"
        f"▪️ Analyzed articles: {analyzed_n}\n\n"
        f"▪️ Mysteel browser: {'OK' if _process_alive('9222') else 'NO'}\n"
        f"▪️ SXCoal browser: {'OK' if _process_alive('9223') else 'NO'}\n"
        f"▪️ Keepalive: {'OK' if _process_alive('browser_keepalive.py') else 'NO'}\n"
    )


def _collect_ai_context():
    if not os.path.exists(DATA_DIR):
        return "Нет данных."

    folders = []
    for x in os.listdir(DATA_DIR):
        p = os.path.join(DATA_DIR, x)
        if os.path.isdir(p):
            folders.append(p)

    if not folders:
        return "Нет данных."

    folders.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    folders = folders[:8]

    parts = []
    for folder in folders:
        ru = os.path.join(folder, "final_summary_ru.txt")
        if os.path.exists(ru):
            try:
                with open(ru, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                if txt:
                    parts.append(f"[{os.path.basename(folder)}]\n{txt}")
            except Exception:
                pass

    return "\n\n".join(parts) if parts else "Нет данных."


def _ask_ai_about_summaries(user_question: str) -> str:
    context = _collect_ai_context()
    debug_text = _build_debug_text()

    prompt = f"""
Вы — аналитический помощник угольного рынка.

Отвечайте строго в деловом стиле, на русском языке.

ЖЁСТКИЕ ПРАВИЛА:
- не используйте символы * или **
- не используйте markdown
- не выделяйте текст звездочками
- пишите обычным текстом
- обращайтесь на Вы
- если данных недостаточно, прямо скажите об этом
- не выдумывайте факты вне контекста

Стиль:
- кратко
- структурировано
- без воды
- как аналитическая записка

Контекст сводок:
{context}

Debug:
{debug_text}

Вопрос:
{user_question}
"""
    resp = client.responses.create(
        model="gpt-5.4-mini",
        input=prompt
    )
    return resp.output_text.strip()


async def _send_start_block(update: Update, chat_id: str):
    text = (
        "⬛ Угольный бот\n\n"
        "▪️ Оперативная сводка публикуется ежедневно в 12:00 по пекинскому времени\n"
        "▪️ Итоговая сводка за весь день публикуется ежедневно в 20:00\n"
        "▪️ Вы можете сформировать оперативную сводку на текущий момент в любое время\n"
        "▪️ Недельная сводка формируется каждую пятницу после 20:00\n"
        "▪️ Месячная сводка формируется в конце каждого месяца\n"
        "▪️ AI-режим позволяет задавать вопросы по сводкам и рыночной ситуации\n\n"
        "▪️ Используйте кнопки ниже или меню команд Telegram."
    )
    await update.message.reply_text(
        text,
        reply_markup=build_reply_keyboard(chat_id in AI_MODE_CHATS)
    )
    await update.message.reply_text("Выберите действие:", reply_markup=build_inline_menu())


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    add_subscriber(chat_id)
    await _send_start_block(update, chat_id)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "⬛ Справка\n\n"
        "▪️ /summary — оперативная сводка на текущий момент\n"
        "▪️ /weekly — недельная сводка\n"
        "▪️ /monthly — месячная сводка\n"
        "▪️ /reports — меню отчётов\n"
        "▪️ /status — статус системы\n"
        "▪️ /debug — техническая диагностика\n"
        "▪️ /ai — включение или выключение AI-режима"
    )
    await update.message.reply_text(text)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    add_subscriber(chat_id)
    await _send_start_block(update, chat_id)


async def cmd_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    add_subscriber(chat_id)
    await update.message.reply_text(
        "Меню отчётов:",
        reply_markup=build_reply_keyboard(chat_id in AI_MODE_CHATS)
    )
    await update.message.reply_text("Выберите действие:", reply_markup=build_inline_menu())


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Формирую оперативную сводку. Это может занять несколько минут...")
    try:
        pair = await asyncio.to_thread(build_manual_summary)
        for chunk in split_long_text(pair["ru"]):
            await update.message.reply_text(chunk, disable_web_page_preview=True)
        if pair.get("zh"):
            for chunk in split_long_text(pair["zh"]):
                await update.message.reply_text(chunk, disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"Ошибка при формировании сводки: {e}")


async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Собираю недельную сводку...")
    text = build_weekly_summary()
    for chunk in split_long_text(text):
        await update.message.reply_text(chunk, disable_web_page_preview=True)


async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Собираю месячную сводку...")
    text = build_monthly_summary()
    for chunk in split_long_text(text):
        await update.message.reply_text(chunk, disable_web_page_preview=True)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    mysteel_ok = _process_alive("9222")
    sxcoal_ok = _process_alive("9223")
    keepalive_ok = _process_alive("browser_keepalive.py")
    week_count = _count_summaries(days=7)
    month_count = _count_summaries(current_month=True)

    text = (
        "⬛ Статус системы\n\n"
        f"▪️ Время: {now}\n"
        f"▪️ Mysteel browser: {'OK' if mysteel_ok else 'NO'}\n"
        f"▪️ SXCoal browser: {'OK' if sxcoal_ok else 'NO'}\n"
        f"▪️ Keepalive: {'OK' if keepalive_ok else 'NO'}\n\n"
        "⬛ Данные:\n"
        f"▪️ Сводок за 7 дней: {week_count}\n"
        f"▪️ За текущий месяц: {month_count}\n\n"
        "⬛ Состояние:\n"
        f"▪️ {'Система стабильна' if (mysteel_ok and sxcoal_ok) else 'Обнаружены проблемы'}"
    )
    await update.message.reply_text(text)


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_build_debug_text())


async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if chat_id in AI_MODE_CHATS:
        AI_MODE_CHATS.remove(chat_id)
        save_ai_mode_chats(AI_MODE_CHATS)
        await update.message.reply_text(
            "AI выключен.",
            reply_markup=build_reply_keyboard(False)
        )
    else:
        AI_MODE_CHATS.add(chat_id)
        save_ai_mode_chats(AI_MODE_CHATS)
        await update.message.reply_text(
            "AI включён.\n\nТеперь Вы можете писать в чат обычные вопросы по рынку угля и последним сводкам.\n\nЧтобы выйти из режима, нажмите кнопку «❌ Выключить AI» или отправьте команду /ai.",
            reply_markup=build_reply_keyboard(True)
        )


async def ai_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    text = (update.message.text or "").strip()

    # 🔥 ВСЕГДА обрабатываем кнопки (даже если AI выключен)
    if text in ["⬛️ Обзор рынка угля", "⬛️ Обзор рынка угля", "старт", "/start"]:
        await _send_start_block(update, chat_id)
        return

    if text in ["🤖 Включить AI", "❌ Выключить AI", "🤖 Режим AI: выкл", "🤖 Режим AI: вкл"]:
        if chat_id in AI_MODE_CHATS:
            AI_MODE_CHATS.remove(chat_id)
            save_ai_mode_chats(AI_MODE_CHATS)
            await update.message.reply_text(
                "AI выключен.",
                reply_markup=build_reply_keyboard(False)
            )
        else:
            AI_MODE_CHATS.add(chat_id)
            save_ai_mode_chats(AI_MODE_CHATS)
            await update.message.reply_text(
                "AI включён.",
                reply_markup=build_reply_keyboard(True)
            )
        return

    if text == "⬛️ Обзор рынка угля":
        await _send_start_block(update, chat_id)
        return

    if text in ["🤖 Включить AI", "❌ Выключить AI", "🤖 Режим AI: выкл", "🤖 Режим AI: вкл"]:
        if chat_id in AI_MODE_CHATS:
            AI_MODE_CHATS.remove(chat_id)
            save_ai_mode_chats(AI_MODE_CHATS)
            await update.message.reply_text(
                "AI выключен.",
                reply_markup=build_reply_keyboard(False)
            )
        else:
            AI_MODE_CHATS.add(chat_id)
            save_ai_mode_chats(AI_MODE_CHATS)
            await update.message.reply_text(
                "AI включён.\n\nТеперь Вы можете писать в чат обычные вопросы по рынку угля и последним сводкам.\n\nЧтобы выйти из режима, нажмите кнопку «❌ Выключить AI» или отправьте команду /ai.",
                reply_markup=build_reply_keyboard(True)
            )
        return

    if chat_id not in AI_MODE_CHATS:
        return

    if not text:
        return

    await update.message.reply_text("Думаю...")
    try:
        answer = _ask_ai_about_summaries(text)
    except Exception as e:
        answer = f"Ошибка AI режима: {e}"

    for chunk in split_long_text(answer):
        await update.message.reply_text(chunk, disable_web_page_preview=True)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = str(query.message.chat_id)
    add_subscriber(chat_id)

    await query.answer()

    if query.data == "manual_summary":
        try:
            recent = get_recent_manual_summary()
            if recent:
                await query.edit_message_text(MANUAL_RECENT_SUMMARY_TEXT)
                await safe_send_pair(chat_id, recent["ru"], recent.get("zh",""), context.bot)
            else:
                await query.edit_message_text("Формирую оперативную сводку. Это может занять несколько минут...")
                pair = await asyncio.to_thread(build_manual_summary)
                await safe_send_pair(chat_id, pair["ru"], pair.get("zh",""), context.bot)
        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"Ошибка при формировании сводки: {e}")

    elif query.data == "weekly_now":
        await query.edit_message_text("Собираю недельную сводку...")
        try:
            text = build_weekly_summary()
            for chunk in split_long_text(text):
                await context.bot.send_message(chat_id=chat_id, text=chunk, disable_web_page_preview=True)
        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"Ошибка weekly: {e}")

    elif query.data == "monthly_now":
        await query.edit_message_text("Собираю месячную сводку...")
        try:
            text = build_monthly_summary()
            for chunk in split_long_text(text):
                await context.bot.send_message(chat_id=chat_id, text=chunk, disable_web_page_preview=True)
        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"Ошибка monthly: {e}")

    elif query.data == "last_midday":
        pair = get_last_scheduled_report("12")
        if not pair:
            pair = {
                "ru": "Сегодняшняя сводка на 12:00 пока ещё не сформирована.",
                "zh": "今天12:00的摘要尚未生成。"
            }
        await safe_send_pair(chat_id, pair["ru"], pair["zh"], context.bot)

    elif query.data == "last_evening":
        pair = get_last_scheduled_report("20")
        if not pair:
            pair = {
                "ru": "Сегодняшняя сводка на 20:00 пока ещё не сформирована.",
                "zh": "今天20:00的摘要尚未生成。"
            }
        await safe_send_pair(chat_id, pair["ru"], pair["zh"], context.bot)

    elif query.data == "status_now":
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        mysteel_ok = _process_alive("9222")
        sxcoal_ok = _process_alive("9223")
        keepalive_ok = _process_alive("browser_keepalive.py")
        week_count = _count_summaries(days=7)
        month_count = _count_summaries(current_month=True)

        text = (
            "⬛ Статус системы\n\n"
            f"▪️ Время: {now}\n"
            f"▪️ Mysteel browser: {'OK' if mysteel_ok else 'NO'}\n"
            f"▪️ SXCoal browser: {'OK' if sxcoal_ok else 'NO'}\n"
            f"▪️ Keepalive: {'OK' if keepalive_ok else 'NO'}\n\n"
            "⬛ Данные:\n"
            f"▪️ Сводок за 7 дней: {week_count}\n"
            f"▪️ За текущий месяц: {month_count}"
        )
        await context.bot.send_message(chat_id=chat_id, text=text)

    elif query.data == "debug_now":
        await context.bot.send_message(chat_id=chat_id, text=_build_debug_text())


async def build_app():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("reports", cmd_reports))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("weekly", cmd_weekly))
    app.add_handler(CommandHandler("monthly", cmd_monthly))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("ai", cmd_ai))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ai_text_handler))
    app.add_handler(MessageHandler(filters.ALL, fallback_handler))
    return app


async def fallback_handler(update, context):
    return


