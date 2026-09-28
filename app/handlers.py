"""Разбор команд: текст пользователя → действие в логике → ответ.

Один класс Bot, который одинаково работает и в консоли, и в MAX -
разница только в переданном transport.
"""
import time

from . import config, db, logic, texts
from .transport import Transport, Update


class Bot:
    def __init__(self, transport: Transport):
        self.tr = transport
        # что бот сейчас ждёт от пользователя: ('answer', question_id, время выдачи)
        self.pending: dict[str, tuple] = {}

    # ─────────────────────────── маршрутизация ───────────────────────────

    def handle(self, u: Update) -> None:
        text = u.text.strip()
        low = text.lower()

        if low in ("/start", "/help", "/старт", "/помощь"):
            return self.tr.send(u.chat_id, texts.HELP)

        if low.startswith("/класс"):
            return self.cmd_create_class(u, text)
        if low.startswith("/вход"):
            return self.cmd_join(u, text)
        if low.startswith("/рейд"):
            return self.cmd_raid(u, text)
        if low.startswith("/бить"):
            return self.cmd_hit(u)
        if low.startswith("/шкала"):
            return self.cmd_progress(u)
        if low.startswith("/арена"):
            return self.cmd_app(u)
        if low.startswith("/вопрос"):
            return self.cmd_new_question(u, text)
        if low.startswith("/проверка"):
            return self.cmd_moderation(u)
        if low.startswith("/одобрить"):
            return self.cmd_moderate(u, text, approve=True)
        if low.startswith("/вернуть"):
            return self.cmd_moderate(u, text, approve=False)
        if low.startswith("/панель"):
            return self.cmd_report(u)
        if low.startswith("/продлить"):
            return self.cmd_extend(u)
        if low.startswith("/библиотека"):
            return self.cmd_library(u, text)
        if low.startswith("/ссылки"):
            return self.cmd_links(u)

        # не команда - значит, это ответ на вопрос
        if u.user_ext_id in self.pending:
            return self.take_answer(u, text)

        self.tr.send(u.chat_id, texts.HELP)

    # ───────────────────────────── учитель ─────────────────────────────

    def cmd_create_class(self, u: Update, text: str) -> None:
        title = text.partition(" ")[2].strip() or "Мой класс"
        cls = logic.create_class(title, u.user_ext_id, u.user_name)
        self.tr.send(u.chat_id, texts.CLASS_CREATED.format(title=title, code=cls["join_code"]))

    def cmd_raid(self, u: Update, text: str) -> None:
        user = self._user(u)
        if not user or user["role"] != "teacher":
            return self.tr.send(u.chat_id, "Объявлять рейды может только учитель.")
        topic = text.partition(" ")[2].strip()
        if not topic:
            return self.tr.send(u.chat_id, "Напишите тему: /рейд Дроби")

        own = logic.bank_size(user["class_id"], topic)
        lib = logic.library_size(user["class_id"], topic)

        if own < config.MIN_BANK_FOR_RAID and own + lib >= config.MIN_BANK_FOR_RAID:
            added = logic.copy_from_library(user["class_id"], topic)
            own = logic.bank_size(user["class_id"], topic)
            self.tr.send(u.chat_id, texts.BANK_ADDED.format(added=added, topic=topic, own=own))
        elif own + lib < config.MIN_BANK_FOR_RAID:
            return self.tr.send(u.chat_id, texts.BANK_THIN.format(topic=topic, own=own, lib=lib))
        else:
            self.tr.send(u.chat_id, texts.BANK_OK.format(topic=topic, own=own, lib=lib),
                         buttons=[f"/библиотека {topic}"] if lib else None)

        raid = logic.create_raid(user["class_id"], topic, days=3)
        self.tr.send(u.chat_id, texts.RAID_STARTED.format(
            topic=raid["topic"], hp=raid["hp_max"], deadline=raid["deadline"]))

    def cmd_links(self, u: Update) -> None:
        """Личные ссылки учеников - для пилота без MAX."""
        user = self._user(u)
        if not user or user["role"] != "teacher":
            return self.tr.send(u.chat_id, "Ссылки класса видит только учитель.")
        cls = db.q1("SELECT * FROM classes WHERE id = ?", user["class_id"])
        base = config.WEBAPP_URL.rstrip("/")
        roster = logic.class_roster(user["class_id"])
        lines = [f"Общая ссылка для входа - раздайте её классу:",
                 f"{base}/join?code={cls['join_code']}", ""]
        if roster:
            lines.append("Личные ссылки тех, кто уже вошёл:")
            lines += [f"{r['name']}: {base}/?t={r['token']}" for r in roster]
            lines.append("")
            lines.append("Личную ссылку никому не пересылайте - по ней бьют от имени ученика.")
        else:
            lines.append("Пока никто не вошёл.")
        self.tr.send(u.chat_id, "\n".join(lines))

    def cmd_library(self, u: Update, text: str) -> None:
        user = self._user(u)
        topic = text.partition(" ")[2].strip()
        added = logic.copy_from_library(user["class_id"], topic)
        self.tr.send(u.chat_id, f"Добавлено {added} вопросов из общей библиотеки.")

    def cmd_moderation(self, u: Update) -> None:
        user = self._user(u)
        items = logic.pending_questions(user["class_id"])
        if not items:
            return self.tr.send(u.chat_id, texts.NOTHING_TO_MODERATE)
        self.tr.send(u.chat_id, "На проверке " + texts.plural(len(items), "вопрос", "вопроса", "вопросов") + ".")
        for q in items:
            self.tr.send(u.chat_id, texts.MODERATION_ITEM.format(
                id=q["id"], author=q["author_name"] or "ученик",
                text=q["text"], answer=q["answer"]),
                buttons=[f"/одобрить {q['id']}", f"/вернуть {q['id']}"])

    def cmd_moderate(self, u: Update, text: str, approve: bool) -> None:
        parts = text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            return self.tr.send(u.chat_id, "Укажите номер: /одобрить 12")
        qid = int(parts[1])
        logic.moderate(qid, approve, reason=" ".join(parts[2:]))
        self.tr.send(u.chat_id, (texts.APPROVED if approve else texts.REJECTED).format(id=qid))

    def cmd_report(self, u: Update) -> None:
        user = self._user(u)
        raid = logic.active_raid(user["class_id"])
        if not raid:
            return self.tr.send(u.chat_id, "Активного рейда нет.")
        rep = logic.raid_report(raid["id"])
        lines = [texts.REPORT.format(
            topic=rep["raid"]["topic"], hp_left=rep["raid"]["hp_left"],
            hp_max=rep["raid"]["hp_max"], participants=rep["participants"],
            total=rep["total_students"], bank=rep["bank"])]
        if rep["weak"]:
            lines.append("\n" + texts.REPORT_WEAK)
            for w in rep["weak"]:
                lines.append(f"· {w['text']} - {w['fails']} ошибок")
        if rep["absentees"]:
            lines.append("\n" + texts.REPORT_ABSENT.format(names=", ".join(rep["absentees"])))
        self.tr.send(u.chat_id, "\n".join(lines), buttons=["/продлить"])

    def cmd_extend(self, u: Update) -> None:
        user = self._user(u)
        raid = logic.active_raid(user["class_id"])
        if not raid:
            return self.tr.send(u.chat_id, "Активного рейда нет.")
        new_date = logic.extend_raid(raid["id"], days=1)
        self.tr.send(u.chat_id, f"Рейд продлён до {new_date}, ученикам ушло уведомление.")

    # ───────────────────────────── ученик ─────────────────────────────

    def cmd_join(self, u: Update, text: str) -> None:
        parts = text.split()
        if len(parts) < 2:
            return self.tr.send(u.chat_id, "Напишите так: /вход 7B-4KM Аня")
        code = parts[1]
        name = " ".join(parts[2:]) or u.user_name
        res = logic.join_class(code, u.user_ext_id, name)
        if not res:
            return self.tr.send(u.chat_id, texts.JOIN_FAILED)
        self.tr.send(u.chat_id, texts.JOINED.format(title=res["class"]["title"]))

    def cmd_hit(self, u: Update) -> None:
        user = self._user(u)
        if not user or not user["class_id"]:
            return self.tr.send(u.chat_id, "Сначала войди в класс: /вход КОД Имя")
        raid = logic.active_raid(user["class_id"])
        if not raid:
            return self.tr.send(u.chat_id, "Сейчас рейда нет. Учитель объявит - пришлём приглашение.")
        q = logic.next_question(raid["id"], user["id"])
        if not q:
            return self.tr.send(u.chat_id, texts.NO_QUESTIONS)
        self.pending[u.user_ext_id] = (raid["id"], q["id"], time.monotonic())
        self.tr.send(u.chat_id, q["text"], buttons=q["options"])

    def take_answer(self, u: Update, given: str) -> None:
        raid_id, question_id, started = self.pending.pop(u.user_ext_id)
        user = self._user(u)
        hit = logic.submit_answer(raid_id, user["id"], question_id, given,
                                  elapsed_sec=time.monotonic() - started)

        if not hit.correct:
            return self.tr.send(u.chat_id, texts.MISS, buttons=["/бить"])
        if hit.skip_reason:
            return self.tr.send(u.chat_id, texts.SKIP_REASONS[hit.skip_reason], buttons=["/бить"])

        self.tr.send(u.chat_id, texts.HIT.format(damage=hit.damage, hp_left=hit.hp_left),
                     buttons=["/бить", "/арена"])
        if hit.victory:
            self.tr.send(u.chat_id, texts.VICTORY)

    def cmd_app(self, u: Update) -> None:
        """Ссылка на мини-приложение со шкалой босса."""
        user = self._user(u)
        if not user or not user["class_id"]:
            return self.tr.send(u.chat_id, "Сначала войди в класс: /вход КОД Имя")
        raid = logic.active_raid(user["class_id"])
        if not raid:
            return self.tr.send(u.chat_id, "Сейчас рейда нет.")
        self.tr.send(u.chat_id, texts.OPEN_APP.format(url=config.WEBAPP_URL))

    def cmd_progress(self, u: Update) -> None:
        user = self._user(u)
        raid = logic.active_raid(user["class_id"])
        if not raid:
            return self.tr.send(u.chat_id, "Сейчас рейда нет.")
        p = logic.class_progress(raid["id"])
        self.tr.send(u.chat_id, texts.PROGRESS.format(
            topic=p["topic"], hp_left=p["hp_left"], hp_max=p["hp_max"],
            deadline=p["deadline"], today=p["contributed_today"], size=p["class_size"]))

    def cmd_new_question(self, u: Update, text: str) -> None:
        """Формат: /вопрос Текст | ответ | вариант1 | вариант2 | вариант3"""
        user = self._user(u)
        raid = logic.active_raid(user["class_id"]) if user else None
        body = text.partition(" ")[2]
        parts = [p.strip() for p in body.split("|") if p.strip()]
        if len(parts) < 3:
            return self.tr.send(
                u.chat_id,
                "Пришли так: /вопрос Сколько будет 2/3 + 1/6? | 5/6 | 5/6 | 3/9 | 1/2\n"
                "Сначала вопрос, потом правильный ответ, потом варианты.")
        topic = raid["topic"] if raid else "Общее"
        logic.submit_question(user["class_id"], user["id"], topic,
                              text=parts[0], answer=parts[1], options=parts[2:])
        self.tr.send(u.chat_id, texts.QUESTION_SENT)

    # ────────────────────────────── служебное ──────────────────────────────

    @staticmethod
    def _user(u: Update) -> dict | None:
        row = db.q1("SELECT * FROM users WHERE ext_id = ?", u.user_ext_id)
        return dict(row) if row else None
