"""Источник компаний — wiki-prom.ru, справочник промышленных предприятий России.

Почему он, а не hh.ru. API hh с 2025 года требует зарегистрированное
приложение, а модерация занимает до 15 рабочих дней — в срок тестового это
не укладывается. wiki-prom отдаёт статический HTML без ключей и капчи, и что
важнее — там ровно тот тип компаний, который нужен: производители, продающие
другим компаниям. B2B по определению, с отделом продаж и потребностью в
клиентах.

Из справочника берём название, домен, адрес, отрасль и состав контактных
блоков. Почту оттуда не берём принципиально: на карточке она скрыта за
JS-вызовом `load_eadr()`, то есть сайт сознательно закрывает её от сборщиков.
Обходить это не нужно и незачем — компании публикуют почту у себя на сайте
открыто, и оттуда она заодно свежее. Этим занимается `site_facts`.

Зато блок «Отдел продаж» на карточке читается из разметки напрямую и работает
как признак квалификации: ТЗ требует компании с отделом продаж, и здесь это
видно, а не предполагается.

Структура сайта: главная -> отрасль (/mr/*.html) -> подкатегория (/NN/*.html)
-> карточка предприятия (/NNNNzavod.html).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http_client import fetch

log = logging.getLogger(__name__)

ROOT = "https://www.wiki-prom.ru/"
CARD_RE = re.compile(r"/(\d+)zavod\.html$")
CATEGORY_RE = re.compile(r"/(\d+)/[a-z0-9-]+\.html$")
INDUSTRY_RE = re.compile(r"/mr/[a-z_]+\.html$")

SOCIAL = re.compile(r"(vk\.com|t\.me|facebook|youtube|ok\.ru|instagram|twitter|"
                    r"yandex\.|google\.|wiki-prom)", re.I)


# Чем заканчивается адрес на карточке: дальше идут контактные блоки.
ADDRESS_END = re.compile(
    r"\s+(?:Приемная|Приёмная|Отдел|Телефон|Факс|Сайт|Дата|показать|Общ|"
    r"Руководител|Электронная|E-?mail|Режим|Продукц)", re.I)


@dataclass
class Company:
    name: str
    website: str = ""
    address: str = ""
    region: str = ""
    industry: str = ""
    departments: list[str] = field(default_factory=list)
    source_url: str = ""

    @property
    def is_russian(self) -> bool:
        """В справочнике есть предприятия сопредельных стран — нам нужна РФ."""
        return "россия" in self.address.lower()

    @property
    def has_sales_department(self) -> bool:
        """ТЗ требует компании с отделом продаж — справочник это показывает."""
        return any("продаж" in d.lower() for d in self.departments)


def _soup(url: str) -> BeautifulSoup | None:
    html = fetch(url)
    return BeautifulSoup(html, "lxml") if html else None


def _links(soup: BeautifulSoup, base: str, pattern: re.Pattern) -> list[str]:
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        url = urljoin(base, a["href"]).split("#")[0]
        if pattern.search(url) and url not in out:
            out.append(url)
    return out


def industry_pages() -> list[str]:
    soup = _soup(ROOT)
    return _links(soup, ROOT, INDUSTRY_RE) if soup else []


def category_pages(industry_url: str) -> list[str]:
    soup = _soup(industry_url)
    return _links(soup, industry_url, CATEGORY_RE) if soup else []


def company_urls(category_url: str) -> list[str]:
    soup = _soup(category_url)
    return _links(soup, category_url, CARD_RE) if soup else []


def parse_company(url: str, industry: str = "") -> Company | None:
    soup = _soup(url)
    if not soup:
        return None

    heading = soup.find("h1")
    name = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip() if heading else ""
    if not name and soup.title:
        name = soup.title.get_text(" ", strip=True).split("|")[0].strip()
    if not name:
        return None

    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    website = ""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and not SOCIAL.search(href):
            website = href.split("/")[2].replace("www.", "").lower()
            break
    if not website:
        # На части карточек домен напечатан текстом без ссылки.
        m = re.search(r"Сайт\s+([a-z0-9][a-z0-9.-]*\.[a-z]{2,6})", text, re.I)
        if m:
            website = m.group(1).lower()

    address = ""
    m = re.search(r"Адрес (?:производства|предприятия|офиса)\s+(\d{6},.{10,220})", text)
    if m:
        chunk = m.group(1)
        end = ADDRESS_END.search(chunk)
        address = (chunk[:end.start()] if end else chunk[:160]).strip(" ,")

    # Названия контактных блоков карточки: «Приемная», «Отдел продаж», …
    departments = [
        re.sub(r"\s+", " ", block.get_text(" ", strip=True))
        for block in soup.select(".cnt-ttl")
    ]

    region = ""
    m = re.search(r"Россия,\s*([^,]*(?:область|край|республика|округ|АО)[^,]*)",
                  address, re.I)
    if m:
        region = m.group(1).strip()
    elif "москва" in address.lower():
        region = "Москва"
    elif "санкт-петербург" in address.lower():
        region = "Санкт-Петербург"

    return Company(name=name, website=website, address=address, region=region,
                   industry=industry, departments=departments, source_url=url)


def collect(limit: int = 60, per_category: int = 8,
            industries: list[str] | None = None) -> list[Company]:
    """Собрать компании, раскладывая выборку по отраслям.

    По `per_category` штук с категории — иначе вся база окажется из одной
    ниши, а для аутрича это плохо: один оффер на 50 одинаковых заводов
    проверяется хуже, чем несколько сегментов.
    """
    out: list[Company] = []
    seen_domains: set[str] = set()

    pages = industries or industry_pages()
    if not pages:
        log.warning("wiki-prom: не удалось получить список отраслей")
        return out

    # Категории всех отраслей и обход по кругу: берём по одной категории из
    # каждой отрасли, потом второй круг и так далее. Если идти отраслями
    # подряд, лимит выбирается на первых двух, и вся база получается из одной
    # ниши — для аутрича это плохо, один оффер на пятьдесят одинаковых заводов
    # проверяется хуже, чем несколько сегментов.
    by_industry: dict[str, list[str]] = {}
    for industry_url in pages:
        industry = industry_url.rstrip(".html").rsplit("/", 1)[-1].replace("_", " ")
        categories = category_pages(industry_url)
        if categories:
            by_industry[industry] = categories
    if not by_industry:
        return out

    queue: list[tuple[str, str]] = []
    for depth in range(max(len(c) for c in by_industry.values())):
        for industry, categories in by_industry.items():
            if depth < len(categories):
                queue.append((industry, categories[depth]))

    for industry, category_url in queue:
        if len(out) >= limit:
            break
        taken = 0
        for card_url in company_urls(category_url):
            if taken >= per_category or len(out) >= limit:
                break
            company = parse_company(card_url, industry=industry)
            if not company or not company.website or not company.is_russian:
                continue
            domain = company.website.lower()
            if domain in seen_domains:
                continue
            seen_domains.add(domain)
            out.append(company)
            taken += 1

    log.info("wiki-prom: собрано %d компаний из %d отраслей",
             len(out), len({c.industry for c in out}))
    return out
