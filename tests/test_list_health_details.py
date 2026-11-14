"""Детали health-проверки списков: домен, файл, системный/ваш, what-to-do."""
from pathlib import Path

from core import list_health


def _mk(root: Path) -> None:
    lists = root / "lists"
    lists.mkdir()
    (lists / "list-general.txt").write_text("a.com\nb.com\n", encoding="utf-8")
    (lists / "list-google.txt").write_text("", encoding="utf-8")
    (lists / "list-discord.txt").write_text("", encoding="utf-8")
    (lists / "list-cdn-fix.txt").write_text("", encoding="utf-8")
    (lists / "list-exclude.txt").write_text("b.com\n", encoding="utf-8")
    (lists / "list-include-user.txt").write_text(
        "a.com\nx.com\nx.com\nconflict.com\n", encoding="utf-8")
    (lists / "list-exclude-user.txt").write_text("conflict.com\n", encoding="utf-8")


def test_health_details_explain_system_and_user_files(tmp_path: Path):
    _mk(tmp_path)
    r = list_health.check_health(tmp_path)

    # подписи и разделение системные/ваши
    assert r["file_labels"]["list-general.txt"] == "системный: общие домены"
    assert r["file_labels"]["list-include-user.txt"] == "ваш: в обход"
    assert "list-general.txt" in r["system_files"]
    assert "list-include-user.txt" in r["user_files"]

    # конфликт: домен в обход (user) и в исключениях (user), оба файла реальные
    conflict = next(c for c in r["conflicts"] if c["entry"] == "conflict.com")
    assert "list-include-user.txt" in conflict["include"]
    assert "list-exclude-user.txt" in conflict["exclude"]
    assert r["total_conflicts"] == 1

    # redundant: a.com уже есть в системном list-general, и это видно
    red = next(x for x in r["redundant"] if x["entry"] == "a.com")
    assert red["file"] == "list-include-user.txt"
    assert red["also_in_files"] == ["list-general.txt"]

    # дубль внутри пользовательского файла
    dup = next(x for x in r["dups"] if x["entry"] == "x.com")
    assert dup["file"] == "list-include-user.txt" and dup["count"] == 2


def test_health_does_not_expose_system_only_conflicts_as_user_totals(tmp_path: Path):
    _mk(tmp_path)
    # конфликт b.com только между системными файлами: в user-итоги не попадает
    r = list_health.check_health(tmp_path)
    assert r["bundled_conflicts"] >= 1
    assert r["total_conflicts"] == 1  # только conflict.com с user-файлами

def test_dedupe_does_not_touch_conflict_only(tmp_path: Path):
    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "list-general.txt").write_text("a.com\n", encoding="utf-8")
    (lists / "list-google.txt").write_text("", encoding="utf-8")
    (lists / "list-discord.txt").write_text("", encoding="utf-8")
    (lists / "list-cdn-fix.txt").write_text("", encoding="utf-8")
    (lists / "list-exclude.txt").write_text("minecraft.net\n", encoding="utf-8")
    (lists / "list-include-user.txt").write_text("minecraft.net\n", encoding="utf-8")
    (lists / "list-exclude-user.txt").write_text("", encoding="utf-8")
    r = list_health.dedupe(tmp_path)
    # Конфликт - не дубль: кнопка «Убрать дубли» не должна ничего удалять.
    assert r["total"] == 0
    assert (lists / "list-include-user.txt").read_text(encoding="utf-8").strip() == "minecraft.net"
