"""Аудит проверяем офлайн: тест не должен зависеть от того, жив ли чужой сайт."""

from src.audit import BROKEN, OK, audit

ROWS = [
    {"company": "HNC", "email": "sales@hnc.su", "website": "hnc.su"},
    {"company": "Tengzhong Machinery", "email": "sales01@nttzmt.com", "website": "uncomtech.ru"},
    {"company": "ТД Ункомтех", "email": "sales@thebestcnc.com", "website": "saintymachine.com"},
    {"company": "Shixinghong Precision", "email": "swyct@126.com", "website": "saintymachine.com"},
]


def _by_company(results, name):
    return next(a for a in results if a.company == name)


def test_consistent_row_passes_clean():
    results = audit(ROWS, verify_online=False)
    hnc = _by_company(results, "HNC")
    assert hnc.status == OK
    assert not hnc.issues
    # Ролевой ящик должен остаться замечанием, а не ошибкой
    assert any("ролевой" in n for n in hnc.notes)


def test_displaced_domain_is_traced_to_its_real_owner():
    results = audit(ROWS, verify_online=False)
    uncomtech = _by_company(results, "ТД Ункомтех")
    assert uncomtech.suggested_domain == "uncomtech.ru"
    assert uncomtech.suggested_owner_row == 2  # сейчас стоит у Tengzhong

    tengzhong = _by_company(results, "Tengzhong Machinery")
    assert tengzhong.domain_claimed_by_other
    assert tengzhong.status == BROKEN


def test_duplicate_website_flagged_on_both_rows():
    results = audit(ROWS, verify_online=False)
    for name in ("ТД Ункомтех", "Shixinghong Precision"):
        assert any("дублируется" in i for i in _by_company(results, name).issues)


def test_offline_run_never_marks_row_ok_by_accident():
    """Без сверки с сайтом статус не должен быть «ok» у явно битой строки."""
    results = audit(ROWS, verify_online=False)
    assert _by_company(results, "Shixinghong Precision").status != OK
