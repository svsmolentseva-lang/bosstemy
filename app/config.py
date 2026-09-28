"""Настройки. Всё, что меняется без правки кода, живёт здесь."""
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- подключение к MAX -------------------------------------------------------
# Токен выдаёт MasterBot в мессенджере MAX по команде /create.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Актуальный адрес платформы. Старый botapi.max.ru отключён - миграция была
# обязательной с 1 октября 2025 года. Токен передаётся в заголовке Authorization,
# а не в адресе (в отличие от Telegram).
# Всё общение с сетью собрано в app/transport.py - если адреса изменятся,
# правится только тот файл.
MAX_API_BASE = os.environ.get("MAX_API_BASE", "https://platform-api.max.ru")

# Адрес мини-приложения: ученик открывает его из чата.
# MAX принимает ТОЛЬКО https и только валидный домен - localhost годится
# лишь для разработки.
WEBAPP_URL = os.environ.get("WEBAPP_URL", "http://localhost:8080")

# Секретный путь вебхука: MAX шлёт события на WEBAPP_URL + этот путь.
# Держите его в тайне - это простейшая защита от чужих запросов.
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/hook/change-me")

# --- хранилище ---------------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "boss.db")

# --- правила игры ------------------------------------------------------------
DEFAULT_RAID_HP = _int("DEFAULT_RAID_HP", 300)

# Урон за один верный ответ.
DAMAGE_PER_HIT = _int("DAMAGE_PER_HIT", 20)

# Ответ быстрее этого - угадывание, урона не даём.
MIN_ANSWER_SECONDS = _int("MIN_ANSWER_SECONDS", 3)

# Сколько ударов в день может нанести один ученик.
# Нужно, чтобы один отличник не выносил босса в одиночку за вечер.
DAILY_HIT_CAP = _int("DAILY_HIT_CAP", 12)

# Вопрос считается сломанным, если на нём ошибается почти каждый.
# За такой вопрос автор очков не получает.
BROKEN_QUESTION_FAIL_RATE = 0.8

# Минимум вопросов, без которого рейд объявлять бессмысленно.
MIN_BANK_FOR_RAID = 10

# Предмет по умолчанию: им помечены данные, заведённые до появления предметов.
DEFAULT_SUBJECT = os.environ.get("DEFAULT_SUBJECT", "Общий")

# Кабинет администратора. Если не задан, при первом запуске сервер напечатает
# сгенерированный токен в консоль - он же сохранится в файле .admin-token.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
