"""Вырезка факта из текста без предложений — плиточные блоки на сайтах."""

from src.site_facts import _tighten_labelled


def test_fact_is_cut_out_of_neighbouring_tiles():
    """Настоящая строка с hnc.su: цифра живёт внутри плитки, вокруг —
    заголовки соседних плиток, точек нет ни одной."""
    snippet = "Гарантия качества На рынке России с 2014 года Консультации Поможем с выбором"
    assert _tighten_labelled(snippet, "с 2014 года") == "На рынке России с 2014 года"


def test_proper_nouns_do_not_cut_a_real_sentence():
    """Обратная сторона: в живой фразе слова с заглавной — города и названия.
    Резать по ним нельзя, поэтому при наличии точки не трогаем вовсе."""
    prose = ("Компания работает в Москве и Санкт-Петербурге с 2010 года, "
             "поставляет оборудование.")
    assert _tighten_labelled(prose, "с 2010 года") == prose


def test_too_few_boundaries_left_as_is():
    plain = "На рынке с 2014 года"
    assert _tighten_labelled(plain, "с 2014 года") == plain
