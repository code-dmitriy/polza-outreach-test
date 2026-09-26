from src.collect import pick_email
from src.site_facts import CompanyFacts
from src.sources.wikiprom import Company


def _facts(emails, domain="zavod.ru"):
    return CompanyFacts(domain=domain, reachable=True, emails=list(emails))


def test_prefers_sales_over_info():
    assert pick_email(_facts(["info@zavod.ru", "sales@zavod.ru"]), "zavod.ru") == "sales@zavod.ru"


def test_prefers_own_domain_over_freemail():
    """Почта на mail.ru рядом с корпоративным сайтом обычно принадлежит
    подрядчику, который делал сайт, а не компании."""
    picked = pick_email(_facts(["zavod2005@mail.ru", "info@zavod.ru"]), "zavod.ru")
    assert picked == "info@zavod.ru"


def test_hr_mailbox_is_last_resort():
    """Коммерческое предложение в отдел кадров — хуже, чем никакого."""
    picked = pick_email(_facts(["hr@zavod.ru", "opt@zavod.ru"]), "zavod.ru")
    assert picked == "opt@zavod.ru"


def test_hr_mailbox_used_when_nothing_else_exists():
    assert pick_email(_facts(["hr@zavod.ru"]), "zavod.ru") == "hr@zavod.ru"


def test_numbered_department_mailbox_still_recognised():
    picked = pick_email(_facts(["hr2@zavod.ru", "sales3@zavod.ru"]), "zavod.ru")
    assert picked == "sales3@zavod.ru"


def test_department_word_in_any_part_of_the_address():
    """mg_job@ — тоже отдел кадров, хотя «job» стоит не первым."""
    picked = pick_email(_facts(["mg_job@zavod.ru", "opt@zavod.ru"]), "zavod.ru")
    assert picked == "opt@zavod.ru"
    picked = pick_email(_facts(["zavod-vacancy@zavod.ru", "info@zavod.ru"]), "zavod.ru")
    assert picked == "info@zavod.ru"


def test_no_emails_returns_empty():
    assert pick_email(_facts([]), "zavod.ru") == ""


def test_sales_department_flag_from_directory_card():
    with_sales = Company(name="Завод", departments=["Приемная", "Отдел продаж"])
    without = Company(name="Завод", departments=["Приемная", "Отдел кадров"])
    assert with_sales.has_sales_department
    assert not without.has_sales_department


def test_russian_address_filter():
    ru = Company(name="Завод", address="652702, Россия, Кемеровская область, г. Киселевск")
    other = Company(name="Завод", address="86000, Украина, Донецкая область")
    assert ru.is_russian
    assert not other.is_russian


def test_complete_rows_come_first():
    """Первая строка таблицы не должна быть пустой: проверяющий увидит её
    раньше всего и решит, что база мусорная."""
    from src.collect import Lead, sort_for_delivery
    from src.emailcheck import check
    from src.site_facts import CompanyFacts

    def lead(name, email="", pers=""):
        l = Lead(company=Company(name=name), facts=CompanyFacts(domain="x.ru"))
        l.email = email
        l.verdict = check(email, check_mx=False) if email else None
        l.personalization = pers
        return l

    empty = lead("Сайт не открылся")
    half = lead("Почта есть, факта нет", "info@x.ru")
    full = lead("Готовая", "sales@x.ru", "Производит станки с 1998 года.")

    order = [l.company.name for l in sort_for_delivery([empty, half, full])]
    assert order == ["Готовая", "Почта есть, факта нет", "Сайт не открылся"]
