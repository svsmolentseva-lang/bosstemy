"""Запуск мини-приложения (экран со шкалой босса).

Разработка без MAX:
    ALLOW_DEV_AUTH=1 python run_web.py
    открыть http://localhost:8080/?u=ext:Аня

В бою пользователь приходит из MAX с подписанными данными - см. app/auth.py.
"""
import os

from app import webapp


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    webapp.serve(port=port)


if __name__ == "__main__":
    main()
