"""Запуск тестов без pytest - на случай, если его нет под рукой.

    python tests/run_without_pytest.py

Если pytest установлен, привычнее:  python -m pytest -q
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# если pytest не установлен, подсовываем минимальную заглушку декоратора fixture
try:
    import pytest  # noqa: F401
except ImportError:
    import types
    shim = types.ModuleType("pytest")

    def _fixture(*a, **kw):
        def deco(fn):
            fn.__wrapped__ = fn
            return fn
        if a and callable(a[0]):
            return deco(a[0])
        return deco

    shim.fixture = _fixture
    sys.modules["pytest"] = shim

from app import config, db  # noqa: E402
import tests.test_logic as t  # noqa: E402


class FakeMonkeypatch:
    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)
        self._undo.clear()


def build_world():
    gen = t.world.__wrapped__()
    return gen, next(gen)


def main() -> int:
    names = [n for n in dir(t) if n.startswith("test_")]
    failed = []
    for name in sorted(names):
        fn = getattr(t, name)
        gen, world = build_world()
        mp = FakeMonkeypatch()
        try:
            if "monkeypatch" in fn.__code__.co_varnames:
                fn(world, mp)
            else:
                fn(world)
            print(f"  ok   {name}")
        except Exception:
            failed.append(name)
            print(f"  FAIL {name}")
            traceback.print_exc()
        finally:
            mp.undo()
            try:
                next(gen)
            except StopIteration:
                pass
            db.close()

    print(f"\n{len(names) - len(failed)} из {len(names)} тестов прошли")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
