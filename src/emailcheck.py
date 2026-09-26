"""Валидация email без внешних сервисов.

Сознательно НЕ делаем SMTP-верификацию: на холодной базе это лишний повод
для хостера получить жалобу, а на catch-all доменах она всё равно врёт.
Ограничиваемся тем, что даёт честный ответ: синтаксис, тип ящика, живость
домена по MX.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import dns.resolver

from .textnorm import registrable_domain

# Упрощённый RFC 5322: практический вариант, ловит реальный мусор
# (двойные @, пробелы, точки по краям) и не отсекает валидные адреса.
_SYNTAX = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

# Ролевые ящики: писать можно, но это не ЛПР — персонализация под человека
# в такие адреса не работает, помечаем отдельно.
ROLE_PREFIXES = {
    "info", "sales", "support", "admin", "office", "contact", "mail", "help",
    "order", "orders", "zakaz", "shop", "hello", "team", "marketing", "pr",
    "job", "jobs", "hr", "noreply", "no-reply", "webmaster", "post", "secretary",
}

# Публичные почтовики: для B2B-аутрича сигнал «микробизнес или частник».
FREEMAIL = {
    "gmail.com", "mail.ru", "bk.ru", "inbox.ru", "list.ru", "yandex.ru",
    "ya.ru", "rambler.ru", "outlook.com", "hotmail.com", "icloud.com",
    "qq.com", "126.com", "163.com", "sina.com", "foxmail.com",
}

DISPOSABLE = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com",
    "trashmail.com", "yopmail.com", "getnada.com", "temp-mail.org",
    "sharklasers.com", "dropmail.me",
}


@dataclass
class EmailVerdict:
    email: str
    domain: str = ""
    syntax_ok: bool = False
    is_role: bool = False
    is_freemail: bool = False
    is_disposable: bool = False
    has_mx: bool | None = None          # None = проверка не проводилась / DNS недоступен
    mx_hosts: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Можно ли вообще отправлять. Ролевой ящик — можно, просто хуже."""
        return self.syntax_ok and not self.is_disposable and self.has_mx is not False


@lru_cache(maxsize=512)
def _mx_lookup(domain: str) -> tuple[str, ...]:
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        return tuple(sorted(str(r.exchange).rstrip(".") for r in answers))
    except Exception:
        return ()


def check(email: str, check_mx: bool = True) -> EmailVerdict:
    email = (email or "").strip().lower()
    v = EmailVerdict(email=email)

    if not email:
        v.problems.append("пустой адрес")
        return v

    v.syntax_ok = bool(_SYNTAX.match(email))
    if not v.syntax_ok:
        v.problems.append("не проходит проверку синтаксиса")
        return v

    local, _, domain = email.partition("@")
    v.domain = domain
    base = local.split("+")[0].split(".")[0]

    v.is_role = base in ROLE_PREFIXES or re.sub(r"\d+$", "", base) in ROLE_PREFIXES
    v.is_freemail = registrable_domain(domain) in FREEMAIL
    v.is_disposable = registrable_domain(domain) in DISPOSABLE

    if v.is_role:
        v.problems.append("ролевой ящик, а не персональный адрес ЛПР")
    if v.is_freemail:
        v.problems.append("публичный почтовый сервис, не корпоративный домен")
    if v.is_disposable:
        v.problems.append("одноразовый домен")

    if check_mx:
        hosts = _mx_lookup(domain)
        v.mx_hosts = list(hosts)
        v.has_mx = bool(hosts)
        if not hosts:
            v.problems.append("у домена нет MX-записи — письмо не доставится")

    return v
