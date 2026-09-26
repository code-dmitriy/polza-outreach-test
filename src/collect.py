"""Задача 1 + 2: собрать базу компаний и сразу её обогатить.

Конвейер: справочник -> сайт компании -> почта -> валидация -> персонализация.

Каждый шаг может ничего не дать (сайт лежит, почты на нём нет), и это
нормально: строка всё равно попадает в таблицу, но с честной пометкой, чего
именно не хватает. Молча выбрасывать такие компании нельзя — по проценту
отсева видно качество источника.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .emailcheck import EmailVerdict
from .emailcheck import check as check_email
from .personalize import build as build_personalization
from .site_facts import CompanyFacts, collect as collect_facts
from .sources.wikiprom import Company
from .textnorm import registrable_domain

log = logging.getLogger(__name__)

# Порядок предпочтения ящиков: сначала те, что ведут в продажи.
MAILBOX_PRIORITY = [
    "sales", "zakaz", "order", "opt", "commerce", "kommerc", "sbyt", "trade",
    "info", "mail", "office", "post", "contact", "secretary", "priemnaya",
]

# Ящики не тех отделов. Коммерческое предложение, ушедшее в отдел кадров или
# в техподдержку, не просто не сработает — оно портит впечатление о компании.
WRONG_DEPARTMENT = (
    "hr", "job", "jobs", "vacancy", "vacancies", "career", "rabota", "kadry",
    "personal", "resume", "cv", "support", "help", "tech", "webmaster",
    "abuse", "postmaster", "noreply", "no-reply", "press", "buh", "accounting",
)

COLUMNS = [
    "Компания", "Сайт", "Контакт", "Email", "Персонализация",
    "Отрасль", "Регион", "Отдел продаж", "Качество почты",
    "Источник факта", "Уверенность", "Карточка в справочнике", "Комментарий",
]


@dataclass
class Lead:
    company: Company
    facts: CompanyFacts | None = None
    email: str = ""
    verdict: EmailVerdict | None = None
    contact: str = ""
    personalization: str = ""
    personalization_source: str = ""
    confidence: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Строка, которую не стыдно отдать в рассылку."""
        return bool(self.email and self.verdict and self.verdict.usable
                    and self.personalization)


def _is_wrong_department(email: str) -> bool:
    """Смотрим все части адреса, а не только первую: отдел кадров пишут и как
    hr@, и как mg_job@, и как zavod-vacancy@."""
    parts = re.split(r"[._+-]", email.partition("@")[0].lower())
    return any(re.sub(r"\d+$", "", part) in WRONG_DEPARTMENT for part in parts if part)


def pick_email(facts: CompanyFacts, website: str) -> str:
    """Выбрать один адрес из найденных на сайте.

    Предпочитаем ящик на домене самой компании: почта на mail.ru рядом с
    корпоративным сайтом чаще всего принадлежит подрядчику, который делал сайт.
    """
    if not facts.emails:
        return ""

    site_domain = registrable_domain(website)
    own = [e for e in facts.emails
           if registrable_domain(e.partition("@")[2]) == site_domain]
    pool = own or facts.emails

    # Ящики чужих отделов берём только если больше ничего нет.
    right_department = [e for e in pool if not _is_wrong_department(e)]
    pool = right_department or pool

    def rank(email: str) -> tuple[int, int]:
        local = email.partition("@")[0].lower()
        for i, prefix in enumerate(MAILBOX_PRIORITY):
            if local.startswith(prefix):
                return (i, len(email))
        return (len(MAILBOX_PRIORITY), len(email))

    return sorted(pool, key=rank)[0]


def build_lead(company: Company, provider: str = "auto", check_mx: bool = True) -> Lead:
    lead = Lead(company=company)

    lead.facts = collect_facts(company.website)
    if not lead.facts.reachable:
        lead.notes.append("сайт не открылся")
        return lead

    lead.email = pick_email(lead.facts, company.website)
    if lead.email:
        lead.verdict = check_email(lead.email, check_mx=check_mx)
        lead.notes.extend(lead.verdict.problems)
        if _is_wrong_department(lead.email):
            lead.notes.append("на сайте только ящик непрофильного отдела — "
                              "перед отправкой поискать контакт продаж вручную")
    else:
        lead.notes.append("на сайте не нашлось ни одного адреса")

    # Имя берём только если компания сама его публикует рядом с должностью.
    if lead.facts.contact_names:
        lead.contact = lead.facts.contact_names[0]
    elif company.has_sales_department:
        lead.contact = "отдел продаж"
        lead.notes.append("персональное имя не публикуется, адресат — отдел продаж")
    else:
        lead.contact = "—"
        lead.notes.append("имя ЛПР на сайте не указано")

    p = build_personalization(company.name, lead.facts, provider=provider)
    lead.personalization = p.text
    lead.personalization_source = p.source_url
    lead.confidence = p.confidence
    if not p.usable:
        lead.notes.append("пригодного факта на сайте нет — письмо без персонализации")

    return lead


def sort_for_delivery(leads: list[Lead]) -> list[Lead]:
    """Готовые строки наверх, недоделанные вниз.

    Порядок внутри групп не трогаем — он даёт чередование отраслей. Смысл
    в первом впечатлении: открывший таблицу должен сразу увидеть рабочие
    контакты, а не строку с неответившим сайтом. Недоделанные при этом
    остаются в файле с объяснением, по ним видно качество источника.
    """
    return sorted(leads, key=lambda lead: (not lead.is_complete, not bool(lead.email)))


def to_rows(leads: list[Lead]) -> list[dict[str, str]]:
    rows = []
    for lead in sort_for_delivery(leads):
        c = lead.company
        quality = "—"
        if lead.verdict:
            if not lead.verdict.usable:
                quality = "непригоден"
            elif lead.verdict.is_role:
                quality = "ролевой, домен живой"
            else:
                quality = "персональный, домен живой"

        rows.append({
            "Компания": c.name,
            "Сайт": c.website,
            "Контакт": lead.contact,
            "Email": lead.email,
            "Персонализация": lead.personalization,
            "Отрасль": c.industry,
            "Регион": c.region,
            "Отдел продаж": "да" if c.has_sales_department else "не указан",
            "Качество почты": quality,
            "Источник факта": lead.personalization_source,
            "Уверенность": lead.confidence,
            "Карточка в справочнике": c.source_url,
            "Комментарий": "; ".join(lead.notes),
        })
    return rows


def write_csv(rows: list[dict[str, str]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path
