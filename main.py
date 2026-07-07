import asyncio
import threading
import time

from storage import ensure_dirs
from telegram_ui import build_app, broadcast_pair
from scheduler import bj_now, get_current_slot_to_send, run_slot, mark_slot_sent


def schedule_loop():
    while True:
        try:
            now = bj_now()
            slot_name = get_current_slot_to_send(now)
            if slot_name:
                pair = run_slot(slot_name)
                if pair:
                    result = broadcast_pair(pair.get("ru", ""), pair.get("zh", ""))
                    print(f"SCHEDULE_BROADCAST slot={slot_name} result={result}")

                    # Anti-spam guard:
                    # if Telegram accepted at least part of the broadcast or returned a non-fatal result,
                    # mark the slot as processed so the scheduler does not resend the same report every 30 seconds.
                    mark_slot_sent(slot_name)
        except Exception as e:
            print(f"Scheduler error: {e}")
        time.sleep(30)


async def run_telegram():
    app = await build_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    ensure_dirs()
    t = threading.Thread(target=schedule_loop, daemon=True)
    t.start()
    asyncio.run(run_telegram())
