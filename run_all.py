"""Бот и мини-приложение в одном процессе.

События от MAX приходят вебхуком на тот же сервер, что отдаёт арену, -
так требует платформа: long polling разрешён только для разработки.

    WEBAPP_URL=https://ваш-домен WEBHOOK_PATH=/hook/секрет BOT_TOKEN=... python run_all.py

После запуска один раз зарегистрируйте адрес вебхука в кабинете разработчика
или методом subscriptions платформы: https://ваш-домен/hook/секрет
"""
import os

from app import db, seed, webapp
from app.handlers import Bot
from app.transport import MaxTransport


def main() -> None:
    db.connect()
    seed.load()

    webapp.BOT = Bot(MaxTransport())
    port = int(os.environ.get("PORT", "8080"))
    print(f"Бот и арена на :{port}, вебхук на {os.environ.get('WEBHOOK_PATH', '/hook/change-me')}")
    webapp.serve(port=port)


if __name__ == "__main__":
    main()
