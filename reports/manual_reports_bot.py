import sys
import asyncio
sys.path.append("/root/coalbot")

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from config import TELEGRAM_BOT_TOKEN
from reports.weekly_report import build_weekly_summary
from reports.monthly_report import build_monthly_summary

BUTTON_WEEKLY = "manual_weekly_now"
BUTTON_MONTHLY = "manual_monthly_now"

async def reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Недельная сейчас", callback_data=BUTTON_WEEKLY)],
        [InlineKeyboardButton("Месячная сейчас", callback_data=BUTTON_MONTHLY)],
    ])
    await update.message.reply_text("Выбери обзор:", reply_markup=kb)

async def on_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

def build_app():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("reports", reports_menu))
    app.add_handler(CallbackQueryHandler(on_click))
    return app

async def main():
    app = build_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
