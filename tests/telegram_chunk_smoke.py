"""Smoke checks for Telegram report sending/chunking."""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telegram_ui import safe_send_pair, split_long_text


class _Bot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, disable_web_page_preview=True):
        self.messages.append(text)


def test_split_long_text_keeps_urls_intact():
    url = "https://example.com/" + "a" * 80
    text = f"⬛ Иные новости\n\n— Baosteel — test item.\nСсылка: {url}\n\n⬛ Следующий блок\nТекст"
    chunks = split_long_text(text, chunk_size=170)
    assert all(len(chunk) <= 170 for chunk in chunks), chunks
    assert sum(url in chunk for chunk in chunks) == 1, chunks
    assert not any("Ссылка: https://example.com/" in chunk and url not in chunk for chunk in chunks), chunks


async def _send_pair():
    bot = _Bot()
    await safe_send_pair("1", "РУССКИЙ ОТЧЕТ", "中文报告", bot)
    return bot.messages


def test_safe_send_pair_separate_messages():
    messages = asyncio.run(_send_pair())
    assert messages == ["РУССКИЙ ОТЧЕТ", "中文报告"], messages
    assert not any("РУССКИЙ ОТЧЕТ\n中文报告" in msg for msg in messages), messages


def main():
    test_split_long_text_keeps_urls_intact()
    test_safe_send_pair_separate_messages()
    print("telegram chunk smoke passed")


if __name__ == "__main__":
    main()
