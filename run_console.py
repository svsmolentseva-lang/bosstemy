"""Тот же бот, но в терминале - для разработки без доступа к MAX.

Запуск:  python run_console.py
Команды: те же, что в мессенджере. Смена пользователя: !кто Аня
"""
import os

from app import db, seed
from app.handlers import Bot
from app.transport import ConsoleTransport, Update

BANNER = """
Босс темы - консольный режим.
Сменить пользователя: !кто Имя        Выйти: !выход

Вы вошли как учитель. Если класс уже заведён (например, скриптом
«пилот.command»), сразу доступны /панель, /проверка и /ссылки.
Если класса ещё нет - начните с /класс 7 «Б».
"""


def ext_id_for(name: str) -> str:
    """Учитель - всегда один и тот же пользователь.

    Иначе «Учитель» в консоли и учитель, заведённый пилотом, оказались бы
    разными людьми, и панель показала бы пустоту.
    """
    return "ext:teacher" if name.strip().lower() in ("учитель", "teacher") else f"ext:{name}"


def main() -> None:
    # По умолчанию работаем с той же базой, что и «пилот.command»,
    # чтобы учитель видел настоящий класс, а не пустую песочницу.
    db.connect(os.environ.get("DB_PATH", os.path.expanduser("~/boss.db")))
    seed.load()

    bot = Bot(ConsoleTransport())
    who = "Учитель"
    print(BANNER)

    while True:
        try:
            line = input(f"\n{who} > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line == "!выход":
            break
        if line.startswith("!кто "):
            who = line[5:].strip() or who
            print(f"- теперь вы {who}")
            continue
        bot.handle(Update(user_ext_id=ext_id_for(who), user_name=who, text=line))

    db.close()


if __name__ == "__main__":
    main()
