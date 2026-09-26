"""Извлечение имён ЛПР. Все примеры — настоящие строки с сайтов из прогона."""

import pytest
from bs4 import BeautifulSoup

from src.site_facts import _extract_names, _looks_like_person


def names(text):
    return _extract_names(BeautifulSoup(f"<p>{text}</p>", "lxml"))


def test_role_then_name():
    assert names("Генеральный директор Сиренко Сергей Михайлович") == [
        "Сиренко Сергей Михайлович (генеральный директор)"]


def test_name_then_role():
    assert names("Иванов Пётр Сергеевич — генеральный директор") == [
        "Иванов Пётр Сергеевич (генеральный директор)"]


def test_previous_phrase_does_not_leak_into_the_name():
    """Из-за re.I на всём шаблоне в базу попадало «холдинга Владимир
    Петрович»: строчное слово подходило под [А-ЯЁ][а-яё]+."""
    result = names("часть крупного холдинга Генеральный директор Пахомов Иван Ильич")
    assert result == ["Пахомов Иван Ильич (генеральный директор)"]
    assert not any("холдинга" in n for n in result)


def test_common_noun_is_not_a_surname():
    assert not _looks_like_person("Розничной Сети")
    assert not _looks_like_person("Торговой Компании")
    assert _looks_like_person("Даов Ислам Газалиевич")
    assert _looks_like_person("Хван Чжэ Хо")


def test_single_word_is_not_a_person():
    assert not _looks_like_person("Иванов")


@pytest.mark.parametrize("role", [
    "Коммерческий директор", "Директор по развитию", "Руководитель отдела продаж",
])
def test_roles_are_recognised(role):
    assert names(f"{role} Петрова Анна Ивановна")


def test_nothing_found_returns_empty_list():
    assert names("Компания производит оборудование для пищевой промышленности") == []
