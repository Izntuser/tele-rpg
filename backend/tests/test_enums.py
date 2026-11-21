import ast
from enum import StrEnum
from pathlib import Path

import app
from app.modules.common import enums

APP_DIR = Path(app.__file__).resolve().parent
ENUMS_FILE = Path(enums.__file__).resolve()


def test_enums_are_defined_only_in_common_enums() -> None:
    """Models and Pydantic schemas must import shared enums, never redefine them."""
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if path.resolve() == ENUMS_FILE:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                bases = {
                    b.id if isinstance(b, ast.Name) else getattr(b, "attr", "") for b in node.bases
                }
                if bases & {"Enum", "StrEnum", "IntEnum"}:
                    offenders.append(f"{path.relative_to(APP_DIR)}:{node.name}")
    assert offenders == []


def test_all_enums_lists_every_enum_once() -> None:
    defined = {
        obj
        for obj in vars(enums).values()
        if isinstance(obj, type) and issubclass(obj, StrEnum) and obj is not StrEnum
    }
    assert set(enums.ALL_ENUMS) == defined
    assert len(enums.ALL_ENUMS) == len(defined)


def test_enum_values_are_lowercase_snake_case() -> None:
    for enum_cls in enums.ALL_ENUMS:
        for member in enum_cls:
            assert member.value == member.value.lower(), (enum_cls, member)
            assert " " not in member.value
