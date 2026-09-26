from src.emailcheck import check


def test_syntax_rejects_obvious_garbage():
    assert not check("test@@mail.ru", check_mx=False).syntax_ok
    assert not check("нет собаки", check_mx=False).syntax_ok
    assert not check("", check_mx=False).syntax_ok


def test_role_mailbox_detected_including_numbered():
    assert check("sales@hnc.su", check_mx=False).is_role
    assert check("sales01@mgwmachine.com", check_mx=False).is_role
    assert not check("n.erhov@example.com", check_mx=False).is_role


def test_freemail_and_disposable():
    assert check("swyct@126.com", check_mx=False).is_freemail
    assert check("a@mailinator.com", check_mx=False).is_disposable


def test_role_mailbox_is_still_usable():
    """Ролевой ящик — минус к качеству, но не повод выбрасывать контакт."""
    v = check("sales@hnc.su", check_mx=False)
    assert v.is_role and v.usable


def test_disposable_is_not_usable():
    assert not check("a@mailinator.com", check_mx=False).usable
