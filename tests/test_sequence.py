from pathlib import Path

import pytest

from src.sequence import WORD_LIMIT, load, render

SEQ = load(Path(__file__).resolve().parent.parent / "data" / "task3_sequence.json")


def test_three_emails_in_the_right_order():
    assert [e.step for e in SEQ.emails] == [1, 2, 3]
    # ТЗ: фолоу-ап через 3 дня, финальный — ещё через 5
    assert [e.day for e in SEQ.emails] == [0, 3, 8]


@pytest.mark.parametrize("email", SEQ.emails, ids=lambda e: f"письмо{e.step}")
def test_word_limit(email):
    assert email.word_count <= WORD_LIMIT, f"{email.word_count} слов"


@pytest.mark.parametrize("email", SEQ.emails, ids=lambda e: f"письмо{e.step}")
def test_subject_and_body_present(email):
    assert email.subject.strip() and email.body.strip()


def test_personalization_variable_used_in_first_email_only():
    """ТЗ требует переменную в письме 1. В фолоу-апах её быть не должно:
    повторять один и тот же факт три раза — верный способ выдать шаблон."""
    assert "{{персонализация}}" in SEQ.emails[0].body
    for email in SEQ.emails[1:]:
        assert "{{персонализация}}" not in email.body


def test_render_leaves_no_unfilled_placeholders():
    text = render(SEQ.emails[0].body, company="Искролайн", name="Иван",
                  personalization="Производит эмиссионные спектрометры.",
                  sender="Никита", fallback=SEQ.personalization_fallback)
    assert "{{" not in text and "}}" not in text


def test_empty_personalization_falls_back_instead_of_leaving_a_hole():
    text = render(SEQ.emails[0].body, personalization="  ",
                  fallback=SEQ.personalization_fallback)
    assert SEQ.personalization_fallback in text
    assert "{{" not in text
