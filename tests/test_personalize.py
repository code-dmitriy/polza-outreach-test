"""Проверяем не то, что персонализация нашлась, а то, что мусор не прошёл.

Все примеры ниже — реальные строки, которые скрипт вытащил с сайтов на
прогоне и которые в письмо попасть не должны.
"""

import pytest

from src.personalize import MIN_USABLE_LENGTH, build
from src.site_facts import CompanyFacts, Fact


def _facts(**kwargs):
    kwargs.setdefault("reachable", True)
    kwargs.setdefault("pages_seen", ["https://zavod.ru"])
    return CompanyFacts(domain="zavod.ru", **kwargs)


def test_real_description_passes():
    p = build("Хайдженик", _facts(
        description="Линейка средств женской гигиены для ежедневного использования "
                    "и в критические дни. Состоят из натуральной целлюлозы.",
        description_source="https://zavod.ru"))
    assert p.usable
    assert "целлюлоз" in p.text


def test_fact_with_a_number_wins_over_description():
    p = build("Завод", _facts(
        description="Мы производим оборудование для пищевой промышленности уже много лет.",
        facts=[Fact(text="Компания работает на рынке России с 2014 года и поставляет "
                         "оборудование более чем в 40 регионов.",
                    kind="год основания", source_url="https://zavod.ru/about")]))
    assert p.confidence == "high"
    assert "2014" in p.text


@pytest.mark.parametrize("junk", [
    "Новости компании и акции",
    "ПКЗ Дубровский - официальный сайт",
])
def test_navigation_scraps_are_rejected(junk):
    assert not build("Завод", _facts(description=junk)).usable


def test_first_person_ad_copy_is_rejected():
    ad = ("Я успел купить кровельные и фасадные материалы по самой низкой цене "
          "в Анапе. Все самое выгодное и качественное только на сайте azkf.ru")
    assert not build("АЗКИФ", _facts(description=ad)).usable


def test_keyword_dump_is_rejected():
    dump = "Ножи, фрезы, свёрла, резцы, пластины, державки, патроны, оправки"
    assert not build("Инструмент", _facts(description=dump)).usable


def test_contact_block_with_phone_is_rejected():
    block = "Отдел продаж +7 (495) 223-06-08 Приемная Электронная почта Режим работы"
    assert not build("Завод", _facts(description=block)).usable


def test_chinese_menu_is_rejected():
    assert not build("Internor", _facts(description="单片刀片湿喷砂机 通过式干喷砂机 烧结炉舟皿")).usable


def test_unreachable_site_gives_nothing_rather_than_guessing():
    p = build("Завод", CompanyFacts(domain="zavod.ru", reachable=False))
    assert not p.usable
    assert p.text == ""


def test_page_header_is_cut_off_not_the_whole_line():
    """Режим работы и хлебные крошки стоят перед текстом. Срезаем шапку,
    а не выбрасываем строку: дальше начинается то, что нужно."""
    raw = ("– Пт.: с 9:00 до 17:00 Главная — О компании ООО ТД «Спецсталь» — "
           "быстроразвивающаяся компания из г. Липецк, начала свою деятельность "
           "в 2009 году с поставок металлопроката.")
    p = build("ТД Спецсталь", _facts(description=raw))
    assert p.usable
    assert p.text.startswith("ООО ТД")
    assert "9:00" not in p.text and "Главная" not in p.text


def test_cms_boilerplate_is_cut_off():
    raw = ("- the dynamic portal engine and content management system. "
           "Эпромет производит катанку и поставляет её более чем ста "
           "корпоративным клиентам, на рынке металлургии десять лет.")
    p = build("Эпромет", _facts(description=raw))
    assert p.usable
    assert "portal engine" not in p.text


@pytest.mark.parametrize("raw, keep, drop", [
    (
        "CONTINENT — один из крупнейших производителей зеркал в России и СНГ. "
        "Официальный сайт производителя зеркал О Компании Партнерам Каталог "
        "Производство Блог Контакты Начать сотрудничество Главная / О компании",
        "производителей зеркал", "Партнерам",
    ),
    (
        "Ecopack - известный итальянский производитель бумажной упаковки для "
        "выпечки, работает с пекарнями и кондитерскими по всей стране. "
        "Наши успехи В ЦИФРАХ 0 лет опыта 0 компетентных сотрудников",
        "бумажной упаковки", "0 лет опыта",
    ),
    (
        "На официальном сайте производителя горного оборудования можно "
        "ознакомиться с продукцией Киселевского завода. каждом элементе "
        "04.03.2025 Чествование людей, внесших вклад",
        "горного оборудования", "04.03.2025",
    ),
])
def test_page_tail_is_cut_off(raw, keep, drop):
    """Осмысленный текст идёт первым, следом приклеивается меню и счётчики.
    Режем по первому маркеру хвоста, а не выбрасываем строку."""
    p = build("Компания", _facts(description=raw))
    assert p.usable
    assert keep in p.text
    assert drop not in p.text


def test_dangling_fragment_is_dropped():
    raw = ("Под брендом Mister Dez произведено более 116 миллионов единиц "
           "продукции за всё время работы компании. которые.")
    p = build("ЕвроТек", _facts(description=raw))
    assert p.usable
    assert not p.text.endswith("которые.")


def test_quoted_title_is_rejected():
    """Название доклада с их страницы новостей — не факт о компании."""
    title = ("«Перспективы развития геномной селекции в племенном животноводстве "
             "молочного и мясного направления продуктивности на 2020-2024г.»")
    assert not build("Тюменьгосплем", _facts(description=title)).usable


def test_discount_offer_is_rejected():
    offer = "Оптовые скидки при заказе соответствующего количества товара."
    assert not build("Центр ремёсел", _facts(description=offer)).usable


def test_fragment_glued_after_fact_is_dropped():
    """Склейка описания с фактом оставляла обрывок вроде «каждом элементе»."""
    p = build("Киселевский завод", _facts(
        description="На сайте производителя горного оборудования можно "
                    "ознакомиться с продукцией Киселевского завода.",
        facts=[Fact(text="каждом элементе", kind="масштаб",
                    source_url="https://zavod.ru")]))
    assert "каждом элементе" not in p.text


def test_lowercase_start_is_capitalised():
    raw = ("фабрика — одно из старейших предприятий Астрахани, образовано "
           "в 1912 году и преобразовано в акционерное общество в 2016 году.")
    p = build("Астраханская фабрика", _facts(description=raw))
    assert p.usable
    assert p.text.startswith("Ф")


def test_too_short_is_not_usable():
    short = "Завод основан давно."
    assert len(short) < MIN_USABLE_LENGTH
    assert not build("Завод", _facts(description=short)).usable


@pytest.mark.parametrize("menu", [
    "Металлочерепица Профлист Фальцевая кровля Ондулин Гибкая черепица Профиль",
    "Стать партнёром Доставка и оплата Полезные материалы Распродажа",
    "Средства для отбеливания Жидкие средства для стирки Средства для стирки Кондиционеры",
    "Продукция Продукция Сертификация добровольная Кадры Кадровая работа СОУТ",
    "Продукции Переключатель меню Прайс листы Гильзовый картон Коробочный картон",
])
def test_stitched_menu_labels_are_rejected(menu):
    """У компании нет описания — и в персонализацию склеиваются названия
    разделов сайта. Формально текст, в письме выдаёт сборщика сразу."""
    assert not build("Завод", _facts(description=menu)).usable


@pytest.mark.parametrize("prose", [
    "С 2008 года и по настоящий день группа компаний ЧСЗ по праву считается крупнейшей в России.",
    "Производство упаковки в Москве. Комбинат Алтайтара выпускает гофрокартон и тару.",
    "Фабрика сетей Люксол — производство капроновых и полипропиленовых сеток, безузловых делей.",
])
def test_prose_with_proper_nouns_survives(prose):
    """Обратная сторона: в живом предложении тоже есть слова с заглавной —
    названия компаний и городов. Их отбрасывать нельзя."""
    assert build("Завод", _facts(description=prose)).usable
