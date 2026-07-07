import os
import sys
from datetime import datetime

sys.path.append("/root/coalbot")

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes

from reports.weekly_report import build_weekly_summary
from reports.monthly_report import build_monthly_summary

BUTTON_WEEKLY = "manual_weekly_now"
BUTTON_MONTHLY = "manual_monthly_now"

DATA_DIR = "/root/coalbot/data_runs"

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
        import subprocess
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📊 Угольный бот\n\n"
        "Доступные команды:\n"
        "/summary — оперативная сводка сейчас\n"
        "/weekly — недельная сводка сейчас\n"
        "/monthly — месячная сводка сейчас\n"
        "/reports — меню отчетов\n"
        "/status — статус системы\n"
        "/help — справка"
    )
    await update.message.reply_text(text)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Справка:\n\n"
        "/summary — последняя готовая оперативная сводка\n"
        "/weekly — недельная сводка по готовым ежедневным сводкам\n"
        "/monthly — месячная сводка по готовым ежедневным сводкам\n"
        "/reports — кнопки для недельной и месячной сводки\n"
        "/status — состояние системы"
    )
    await update.message.reply_text(text)

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = _latest_summary_text()
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i+4000], disable_web_page_preview=True)

async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Собираю недельную сводку...")
    text = build_weekly_summary()
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i+4000], disable_web_page_preview=True)

async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Собираю месячную сводку...")
    text = build_monthly_summary()
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i+4000], disable_web_page_preview=True)

async def cmd_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Недельная сейчас", callback_data=BUTTON_WEEKLY)],
        [InlineKeyboardButton("Месячная сейчас", callback_data=BUTTON_MONTHLY)],
    ])
    await update.message.reply_text("Выбери обзор:", reply_markup=kb)

async def on_reports_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == BUTTON_WEEKLY:
        await query.message.reply_text("Собираю недельную сводку...")
        text = build_weekly_summary()
        for i in range(0, len(text), 4000):
            await query.message.reply_text(text[i:i+4000], disable_web_page_preview=True)

    elif query.data == BUTTON_MONTHLY:
        await query.message.reply_text("Собираю месячную сводку...")
        text = build_monthly_summary()
        for i in range(0, len(text), 4000):
            await query.message.reply_text(text[i:i+4000], disable_web_page_preview=True)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mysteel_ok = _process_alive("9222")
    sxcoal_ok = _process_alive("9223")
    keepalive_ok = _process_alive("browser_keepalive.py")
    week_count = _count_summaries(days=7)
    month_count = _count_summaries(current_month=True)

    text = (
        "Статус системы:\n"
        f"— Mysteel browser: {'OK' if mysteel_ok else 'NO'}\n"
        f"— SXCoal browser: {'OK' if sxcoal_ok else 'NO'}\n"
        f"— Keepalive: {'OK' if keepalive_ok else 'NO'}\n"
        f"— Сводок за 7 дней: {week_count}\n"
        f"— Сводок за текущий месяц: {month_count}"
    )
    await update.message.reply_text(text)

def register_report_handlers(app):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("weekly", cmd_weekly))
    app.add_handler(CommandHandler("monthly", cmd_monthly))
    app.add_handler(CommandHandler("reports", cmd_reports))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(on_reports_click, pattern=f"^({BUTTON_WEEKLY}|{BUTTON_MONTHLY})$"))
