"""Бот через long polling - только для разработки.

Платформа MAX разрешает long polling лишь на этапе отладки; для боевого
режима используйте run_all.py с вебхуком.
"""
from app import db, seed
from app.handlers import Bot
from app.transport import MaxTransport


def main() -> None:
    db.connect()
    seed.load()
    bot = Bot(MaxTransport())
    print("Бот запущен в режиме разработки (long polling), ждём сообщения…")
    bot.tr.poll(bot.handle)


if __name__ == "__main__":
    main()
