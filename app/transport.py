"""Связь с внешним миром.

Вся сеть живёт только здесь. Логика игры про мессенджер ничего не знает,
поэтому её можно гонять в консоли без токена - этим и занимается
ConsoleTransport.

ВАЖНО: точные адреса методов MAX Bot API нужно сверить с документацией
на dev.max.ru перед первым запуском. Если они отличаются - правится
только MaxTransport, остальной код не трогается.
"""
from typing import Callable

from . import config


class Update:
    """Одно входящее событие: кто написал и что."""

    def __init__(self, user_ext_id: str, user_name: str, text: str, chat_id: str | None = None):
        self.user_ext_id = user_ext_id
        self.user_name = user_name
        self.text = text
        self.chat_id = chat_id or user_ext_id

    def __repr__(self) -> str:
        return f"<Update {self.user_name}: {self.text!r}>"


class Transport:
    """Интерфейс, который использует бот."""

    def send(self, chat_id: str, text: str, buttons: list[str] | None = None) -> None:
        raise NotImplementedError

    def poll(self, handler: Callable[[Update], None]) -> None:
        raise NotImplementedError


class ConsoleTransport(Transport):
    """Эмулятор мессенджера в терминале: пишем боту, читаем ответы.

    Нужен, чтобы разрабатывать и показывать логику, пока нет доступа к MAX.
    """

    def __init__(self):
        self.log: list[tuple[str, str]] = []

    def send(self, chat_id: str, text: str, buttons: list[str] | None = None) -> None:
        self.log.append((chat_id, text))
        print(f"\n[бот → {chat_id}]\n{text}")
        if buttons:
            print("  " + "   ".join(f"[{b}]" for b in buttons))

    def poll(self, handler: Callable[[Update], None]) -> None:
        raise NotImplementedError("Консольный режим управляется из run_console.py")


class MaxTransport(Transport):
    """Работа с MAX Bot API.

    Токен передаётся в заголовке (в отличие от Telegram, где он в адресе).
    Long polling разрешён только для разработки: в проде нужен вебхук.
    """

    def __init__(self, token: str | None = None, base: str | None = None):
        import httpx  # нужен только для работы с сетью; консоль и веб обходятся без него

        self.token = token or config.BOT_TOKEN
        self.base = (base or config.MAX_API_BASE).rstrip("/")
        if not self.token:
            raise RuntimeError("Не задан BOT_TOKEN - получите его у MasterBot в MAX")
        self.client = httpx.Client(
            base_url=self.base,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30.0,
        )
        self.marker: int | None = None

    def send(self, chat_id: str, text: str, buttons: list[str] | None = None) -> None:
        payload: dict = {"text": text}
        if buttons:
            payload["attachments"] = [{
                "type": "inline_keyboard",
                "payload": {"buttons": [[{"type": "callback", "text": b, "payload": b}] for b in buttons]},
            }]
        self.client.post("/messages", params={"chat_id": chat_id}, json=payload)

    def poll(self, handler: Callable[[Update], None]) -> None:
        """Long polling. Для продакшена заменить на вебхук."""
        while True:
            params: dict = {"timeout": 30}
            if self.marker:
                params["marker"] = self.marker
            data = self.client.get("/updates", params=params).json()
            self.marker = data.get("marker", self.marker)
            for raw in data.get("updates", []):
                update = self._parse(raw)
                if update:
                    handler(update)

    @staticmethod
    def _parse(raw: dict) -> Update | None:
        """Разбор события. Структуру сверить с dev.max.ru."""
        sender = (raw.get("message", {}).get("sender")
                  or raw.get("callback", {}).get("user") or {})
        ext_id = str(sender.get("user_id") or "")
        if not ext_id:
            return None
        name = sender.get("first_name") or sender.get("name") or "Ученик"
        text = (raw.get("message", {}).get("body", {}).get("text")
                or raw.get("callback", {}).get("payload") or "")
        chat_id = str(raw.get("message", {}).get("recipient", {}).get("chat_id") or ext_id)
        return Update(ext_id, name, text, chat_id)
