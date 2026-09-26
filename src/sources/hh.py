"""Источник компаний — открытый API hh.ru.

Почему именно он. По ТЗ нужны российские B2B-компании, у которых есть отдел
продаж. Компания, которая прямо сейчас публикует вакансию менеджера по
продажам, этот критерий доказывает сама: отдел есть и его расширяют. Заодно
это и есть портрет клиента Polza Agency — тот, кому нужен поток заявок.

Ключ не нужен, лимиты щадящие, данные публичные. Из вакансии берём только
работодателя, сам текст вакансии и контакты рекрутёра не используем: это
данные для найма, а не для холодных продаж.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..http_client import fetch_json

log = logging.getLogger(__name__)

API = "https://api.hh.ru"
AREA_RUSSIA = 113

# Запросы подобраны так, чтобы попадать в компании с живым отделом продаж
# в разных отраслях, а не выгребать один и тот же кадровый агрегатор.
DEFAULT_QUERIES = [
    "менеджер по продажам B2B",
    "руководитель отдела продаж",
    "менеджер по работе с ключевыми клиентами",
    "развитие продаж производство",
    "менеджер по продажам оборудование",
    "менеджер по продажам логистика",
    "менеджер по продажам IT решения",
    "sales manager B2B",
]

# Кадровые агентства и агрегаторы: у них «отдел продаж» есть, но клиентами
# Polza Agency они не будут — это прямые конкуренты по лидгену.
BLOCKLIST_WORDS = {
    "кадровое агентство", "агентство по подбору", "аутстаффинг", "рекрутинг",
    "recruitment", "hh.ru", "headhunter", "вакансии", "работа.ру",
}


@dataclass
class Employer:
    hh_id: str
    name: str
    site_url: str = ""
    area: str = ""
    industries: list[str] = field(default_factory=list)
    description_html: str = ""
    open_vacancies: int = 0
    hh_url: str = ""

    @property
    def is_usable(self) -> bool:
        if not self.site_url:
            return False
        lowered = self.name.lower()
        return not any(word in lowered for word in BLOCKLIST_WORDS)


def search_employer_ids(queries: list[str] | None = None, pages: int = 2,
                        per_page: int = 100) -> list[str]:
    """Собрать id работодателей из выдачи вакансий. Порядок сохраняем,
    дубли убираем — одна компания часто висит сразу с несколькими вакансиями."""
    ids: list[str] = []
    for query in queries or DEFAULT_QUERIES:
        for page in range(pages):
            data = fetch_json(f"{API}/vacancies", {
                "text": query,
                "area": AREA_RUSSIA,
                "per_page": per_page,
                "page": page,
                "only_with_salary": "false",
                "search_field": "name",
            })
            if not data or not data.get("items"):
                break
            for item in data["items"]:
                employer = item.get("employer") or {}
                eid = employer.get("id")
                if eid and eid not in ids:
                    ids.append(eid)
            if page + 1 >= data.get("pages", 0):
                break
    log.info("hh: найдено работодателей — %d", len(ids))
    return ids


def get_employer(hh_id: str) -> Employer | None:
    data = fetch_json(f"{API}/employers/{hh_id}")
    if not data or not data.get("name"):
        return None
    return Employer(
        hh_id=hh_id,
        name=data["name"].strip(),
        site_url=(data.get("site_url") or "").strip(),
        area=((data.get("area") or {}).get("name") or ""),
        industries=[i.get("name", "") for i in (data.get("industries") or [])],
        description_html=data.get("description") or "",
        open_vacancies=data.get("open_vacancies") or 0,
        hh_url=data.get("alternate_url") or "",
    )


def collect_employers(limit: int, queries: list[str] | None = None,
                      pages: int = 2) -> list[Employer]:
    """Работодатели с указанным сайтом, без кадровых агентств."""
    out: list[Employer] = []
    seen_domains: set[str] = set()

    for hh_id in search_employer_ids(queries, pages=pages):
        if len(out) >= limit:
            break
        employer = get_employer(hh_id)
        if not employer or not employer.is_usable:
            continue
        # Холдинги заводят по юрлицу на бренд — по домену дубли видно надёжнее.
        from ..textnorm import registrable_domain
        domain = registrable_domain(employer.site_url)
        if not domain or domain in seen_domains:
            continue
        seen_domains.add(domain)
        out.append(employer)

    log.info("hh: пригодных работодателей — %d", len(out))
    return out
