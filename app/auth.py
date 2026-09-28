"""Кто открыл мини-приложение.

В бою MAX передаёт мини-приложению данные о пользователе через MAX Bridge:
на странице появляется глобальный объект window.WebApp, а в нём initData
(строка со всеми параметрами запуска) и initDataUnsafe. Проверять подпись
initData обязательно: иначе любой откроет чужой экран, подставив имя в адресе.

ТОЧНЫЙ ФОРМАТ ПОДПИСИ НУЖНО СВЕРИТЬ С dev.max.ru - заглушка ниже честно
падает, пока это не сделано. До тех пор работает режим разработки:
ALLOW_DEV_AUTH=1 и ?u=ext:Аня в адресе.
"""
import hashlib
import hmac
import os

from . import config, db


def identify(query: dict, headers=None) -> dict:
    """Возвращает пользователя из базы или бросает PermissionError."""
    init_data = _first(query, "init_data")
    if init_data:
        ext_id, name = verify_max_init(init_data)
        return _user_by_ext(ext_id, name)

    # личная ссылка пилота: у каждого ученика свой секрет
    token = _first(query, "t")
    if token:
        from . import logic
        user = logic.user_by_token(token)
        if not user:
            raise PermissionError("ссылка недействительна - попросите новую у учителя")
        if not user["class_id"] and not _teaches_somewhere(user):
            raise PermissionError("вы ещё не в классе")
        return user

    if os.environ.get("ALLOW_DEV_AUTH") == "1":
        ext = _first(query, "u")
        if ext:
            return _user_by_ext(ext, ext.split(":")[-1])

    raise PermissionError("не удалось определить пользователя")


def verify_max_init(init_data: str) -> tuple[str, str]:
    """Проверка подписи MAX Bridge.

    Схема ниже написана по аналогии с тем, как это устроено в похожих
    платформах, и НЕ ПРОВЕРЕНА на реальном MAX. Перед запуском в бою:
    сверить с документацией, прогнать на живых данных, только потом убирать
    ALLOW_DEV_AUTH.
    """
    raise NotImplementedError(
        "Проверка подписи MAX Bridge не реализована - сверьте формат с dev.max.ru"
    )


def _sign(data: str, secret: bytes) -> str:
    return hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()


def _bot_secret() -> bytes:
    return hashlib.sha256(config.BOT_TOKEN.encode()).digest()


def _first(query: dict, key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _teaches_somewhere(user: dict) -> bool:
    """У учителя нескольких классов class_id пустой - классы лежат в teaching."""
    if user.get("role") != "teacher":
        return False
    return db.q1("SELECT 1 FROM teaching WHERE teacher_id = ?", user["id"]) is not None


def _user_by_ext(ext_id: str, fallback_name: str) -> dict:
    row = db.q1("SELECT * FROM users WHERE ext_id = ?", ext_id)
    if not row:
        raise PermissionError("пользователь не найден - сначала войдите в класс через бота")
    user = dict(row)
    if not user["class_id"] and not _teaches_somewhere(user):
        raise PermissionError("вы ещё не в классе")
    return user
