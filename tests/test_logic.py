"""Тесты правил игры. Запуск: python -m pytest -q

Сеть не нужна: логика ничего не знает про мессенджер.
"""
import os
import tempfile

import pytest

from app import config, db, logic, seed


@pytest.fixture()
def world():
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    db.connect(path)
    seed.load()
    cls = logic.create_class("7 «Б»", "ext:teacher", "Учитель")
    logic.copy_from_library(cls["id"], "Дроби")
    students = [logic.join_class(cls["join_code"], f"ext:s{i}", f"Ученик{i}")["user"]
                for i in range(5)]
    raid = logic.create_raid(cls["id"], "Дроби", days=3, hp=100)
    yield {"class": cls, "students": students, "raid": raid}
    db.close()


def answer(world, student, correct=True, elapsed=10.0):
    q = logic.next_question(world["raid"]["id"], student["id"])
    given = q["answer"] if correct else "заведомо неверно"
    return logic.submit_answer(world["raid"]["id"], student["id"], q["id"], given, elapsed), q


def test_correct_answer_deals_damage(world):
    hit, _ = answer(world, world["students"][0])
    assert hit.correct
    assert hit.damage == config.DAMAGE_PER_HIT
    assert hit.hp_left == 100 - config.DAMAGE_PER_HIT


def test_wrong_answer_deals_nothing(world):
    hit, _ = answer(world, world["students"][0], correct=False)
    assert not hit.correct
    assert hit.damage == 0
    assert hit.hp_left == 100


def test_too_fast_is_not_counted(world):
    hit, _ = answer(world, world["students"][0], elapsed=0.5)
    assert hit.correct
    assert hit.damage == 0
    assert hit.skip_reason == "too_fast"


def test_repeat_answer_gives_no_second_damage(world):
    raid_id = world["raid"]["id"]
    student = world["students"][0]
    q = logic.next_question(raid_id, student["id"])
    first = logic.submit_answer(raid_id, student["id"], q["id"], q["answer"], 10.0)
    second = logic.submit_answer(raid_id, student["id"], q["id"], q["answer"], 10.0)
    assert first.damage == config.DAMAGE_PER_HIT
    assert second.damage == 0
    assert second.skip_reason == "repeat"


def test_daily_cap_stops_one_person_soloing(world, monkeypatch):
    monkeypatch.setattr(config, "DAILY_HIT_CAP", 2)
    student = world["students"][0]
    damages = [answer(world, student)[0].damage for _ in range(4)]
    assert damages[:2] == [config.DAMAGE_PER_HIT] * 2
    assert damages[2:] == [0, 0]


def test_class_together_wins(world):
    """Пятеро учеников добивают босса - и рейд закрывается победой."""
    won = False
    for _ in range(3):
        for student in world["students"]:
            hit, _ = answer(world, student)
            won = won or hit.victory
    raid = db.q1("SELECT * FROM raids WHERE id = ?", world["raid"]["id"])
    assert won
    assert raid["status"] == "won"
    assert raid["hp_left"] == 0


def test_damage_never_goes_below_zero(world):
    db.run("UPDATE raids SET hp_left = 5 WHERE id = ?", world["raid"]["id"])
    hit, _ = answer(world, world["students"][0])
    assert hit.damage == 5
    assert hit.hp_left == 0


def test_report_lists_absentees_and_weak_spots(world):
    active = world["students"][:2]
    for student in active:
        answer(world, student, correct=False)
        answer(world, student, correct=True)

    rep = logic.raid_report(world["raid"]["id"])
    assert rep["total_students"] == 5
    assert rep["participants"] == 2
    assert len(rep["absentees"]) == 3


def test_one_mistake_does_not_become_a_verdict(world):
    """Одна ошибка одного ребёнка не попадает ни в подтемы, ни в вопросы."""
    answer(world, world["students"][0], correct=False)
    rep = logic.raid_report(world["raid"]["id"])
    assert rep["weak"] == []
    assert rep["skills"] == []


def test_report_groups_mistakes_by_skill(world):
    """Когда на одном вопросе спотыкается класс, видно подтему и пример."""
    raid_id = world["raid"]["id"]
    q = logic.next_question(raid_id, world["students"][0]["id"])
    for student in world["students"]:
        logic.submit_answer(raid_id, student["id"], q["id"], "заведомо неверно", 10.0)

    rep = logic.raid_report(raid_id)
    assert rep["skills"], "подтема должна попасть в отчёт"
    top = rep["skills"][0]
    assert top["share"] == 100
    assert top["asked"] == 5
    assert top["sample"] == q["text"]
    assert rep["weak"][0]["share"] == 100


def test_student_question_waits_for_moderation(world):
    author = world["students"][0]
    qid = logic.submit_question(world["class"]["id"], author["id"], "Дроби",
                                "1/2 + 1/2 = ?", "1", ["1", "2/4", "1/4"])
    pending = logic.pending_questions(world["class"]["id"])
    assert [p["id"] for p in pending] == [qid]

    logic.moderate(qid, approve=True)
    assert logic.pending_questions(world["class"]["id"]) == []
    assert db.q1("SELECT status FROM questions WHERE id = ?", qid)["status"] == "approved"


def test_broken_question_earns_author_nothing(world):
    """Если на вопросе спотыкаются почти все - он сломан, а не хитёр."""
    author = world["students"][0]
    qid = logic.submit_question(world["class"]["id"], author["id"], "Дроби",
                                "Непонятный вопрос", "42", ["42", "1", "2"])
    logic.moderate(qid, approve=True)
    for student in world["students"]:
        logic.submit_answer(world["raid"]["id"], student["id"], qid, "мимо", 10.0)
    assert logic.author_score(qid) == 0


def test_good_question_earns_author_points(world):
    author = world["students"][0]
    qid = logic.submit_question(world["class"]["id"], author["id"], "Дроби",
                                "Хитрый вопрос", "5/6", ["5/6", "1/2", "2/3"])
    logic.moderate(qid, approve=True)
    others = world["students"][1:]
    logic.submit_answer(world["raid"]["id"], others[0]["id"], qid, "мимо", 10.0)
    logic.submit_answer(world["raid"]["id"], others[1]["id"], qid, "5/6", 10.0)
    logic.submit_answer(world["raid"]["id"], others[2]["id"], qid, "5/6", 10.0)
    assert logic.author_score(qid) == 1


def test_clone_raid_copies_questions(world):
    other = logic.create_class("7 «А»", "ext:teacher2", "Учитель2")
    assert logic.bank_size(other["id"], "Дроби") == 0
    logic.clone_raid(world["raid"]["id"], other["id"], days=2)
    assert logic.bank_size(other["id"], "Дроби") > 0
    assert logic.active_raid(other["id"]) is not None


def test_join_code_is_unique_and_readable(world):
    codes = {logic.make_join_code() for _ in range(50)}
    assert len(codes) == 50
    for code in codes:
        assert "-" in code
        assert not set(code) & set("O0I1")


def test_library_questions_have_four_options(world):
    """В каждом вопросе ровно четыре варианта, один верный и указана подтема."""
    from app import seed
    for topic, skill, text, answer, options in seed.LIBRARY:
        assert len(options) == 4, f"{text}: вариантов {len(options)}, а нужно 4"
        assert len(set(options)) == 4, f"{text}: варианты повторяются"
        assert options.count(answer) == 1, f"{text}: верный ответ не один"
        assert skill.strip(), f"{text}: не указана подтема"


def test_library_options_are_not_equal_by_value(world):
    """Дроби вроде 6/8 и 3/4 равны по значению - таких пар быть не должно."""
    import re
    from fractions import Fraction
    from app import seed

    def value(text):
        text = text.strip().replace(",", ".")
        m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", text)
        if m:
            return Fraction(int(m.group(1)), int(m.group(2)))
        try:
            return Fraction(text)
        except Exception:
            return None

    for topic, skill, text, answer, options in seed.LIBRARY:
        right = value(answer)
        if right is None:
            continue
        twins = [o for o in options if o != answer and value(o) == right]
        assert not twins, f"{text}: {twins} равны верному ответу"
