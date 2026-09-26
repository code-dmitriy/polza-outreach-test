"""Достать с сайта компании то, из чего можно собрать честную персонализацию.

Правило одно: ничего не выдумываем. Всё, что попадает в итоговый текст,
должно иметь адрес страницы, откуда оно взято, — поэтому у каждого факта
хранится `source_url`, и он едет в таблицу отдельной колонкой. Проверяющий
должен иметь возможность ткнуть в ссылку и увидеть тот же текст.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .http_client import fetch

log = logging.getLogger(__name__)

# Куда ходим за контактами и «о компании» — типовые адреса рунета и англоязычных сайтов.
CONTACT_PATHS = [
    "", "/contacts", "/contacts/", "/kontakty", "/kontakty/", "/contact",
    "/contact-us", "/about", "/about/", "/about-us", "/o-kompanii",
    "/o-nas", "/company", "/company/", "/rukovodstvo", "/team", "/komanda",
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Мусорные адреса из шаблонов, CDN и примеров в вёрстке.
EMAIL_NOISE = re.compile(
    r"(example\.|sentry\.|wixpress|\.png$|\.jpg$|\.webp$|\.gif$|\.svg$"
    r"|@sentry|@2x|domain\.com|your-?mail|mail@mail)", re.I
)

# Конкретика, на которой держится персонализация: цифры и даты, а не прилагательные.
FACT_PATTERNS = [
    (re.compile(r"(?:с|в)\s+(19[5-9]\d|20[0-2]\d)\s*год", re.I), "год основания"),
    (re.compile(r"(?:более|свыше|больше)\s+([\d\s]{2,9})\s*(клиент\w*|компан\w*|проект\w*|заказ\w*|сотрудник\w*)", re.I), "масштаб"),
    (re.compile(r"(\d{1,3})\s*(?:лет|года)\s+(?:на рынке|опыта|работы)", re.I), "опыт"),
    (re.compile(r"(\d{1,4})\s*(?:филиал\w*|склад\w*|завод\w*|офис\w*)\s", re.I), "инфраструктура"),
]


@dataclass
class Fact:
    text: str
    kind: str
    source_url: str


@dataclass
class CompanyFacts:
    domain: str
    reachable: bool = False
    title: str = ""
    description: str = ""          # meta description / og:description
    description_source: str = ""
    headline: str = ""             # первый h1/h2
    lead_paragraph: str = ""       # первый содержательный абзац — запасной источник
    lead_source: str = ""
    emails: list[str] = field(default_factory=list)
    email_sources: dict[str, str] = field(default_factory=dict)
    contact_names: list[str] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    pages_seen: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _extract_emails(html: str, soup: BeautifulSoup) -> list[str]:
    found: list[str] = []
    for a in soup.select('a[href^="mailto:"]'):
        addr = a["href"][7:].split("?")[0].strip()
        if addr:
            found.append(addr)
    found.extend(EMAIL_RE.findall(html))

    out: list[str] = []
    for addr in found:
        addr = addr.strip(".,;:()<>\"'").lower()
        if EMAIL_NOISE.search(addr) or addr in out:
            continue
        # Отсекаем «хвосты» вида info@site.comЗвоните
        if len(addr) > 80:
            continue
        out.append(addr)
    return out


# Слова, которые встают на место фамилии: это хвост предыдущей фразы,
# прилипший к должности при разборе сплошного текста страницы.
_NOT_A_NAME = {
    "холдинг", "холдинга", "сеть", "сети", "компания", "компании", "группа",
    "группы", "завод", "завода", "фабрика", "фабрики", "отдел", "отдела",
    "предприятие", "предприятия", "производство", "производства", "общество",
    "россия", "россии", "москва", "москвы", "директор", "директора",
    "руководитель", "основатель", "владелец", "розничной", "оптовой",
    "торговой", "управляющей", "дочерней", "нашей", "своей", "этой",
}

_ROLES = (
    r"генеральн\w+ директор|коммерческ\w+ директор|исполнительн\w+ директор|"
    r"директор по развитию|директор по продажам|руководител\w+ отдела продаж|"
    r"ген\.?\s*директор|основател\w+|владелец|собственник"
)

# Регистр в имени значим. Под общим флагом re.I шаблон [А-ЯЁ][а-яё]+ ловит
# любое слово, и в имя уезжает конец предыдущего предложения — так в базе
# появился «холдинга Владимир Петрович». Поэтому нечувствительность к
# регистру включаем только на названии должности.
_NAME = r"[А-ЯЁ][а-яё]{2,}(?:\s+[А-ЯЁ][а-яё]{2,}){1,2}"

_ROLE_THEN_NAME = re.compile(rf"(?i:({_ROLES}))[\s\-–—:,]+({_NAME})")
_NAME_THEN_ROLE = re.compile(rf"({_NAME})\s*[,\-–—:]\s*(?i:({_ROLES}))")


def _looks_like_person(name: str) -> bool:
    words = name.split()
    if not 2 <= len(words) <= 3:
        return False
    return all(word.lower() not in _NOT_A_NAME for word in words)


def _extract_names(soup: BeautifulSoup) -> list[str]:
    """Имена ЛПР, если компания сама их публикует рядом с должностью.

    Берём только то, что напечатано на сайте самой компании: никакого
    сведения профилей из разных источников мы не делаем.
    """
    text = _clean(soup.get_text(" ", strip=True))
    found: list[tuple[str, str]] = []

    for role, name in _ROLE_THEN_NAME.findall(text):
        found.append((name, role))
    for name, role in _NAME_THEN_ROLE.findall(text):
        found.append((name, role))

    names: list[str] = []
    for name, role in found:
        name = _clean(name)
        if not _looks_like_person(name):
            continue
        entry = f"{name} ({_clean(role).lower()})"
        if entry not in names:
            names.append(entry)
    return names[:3]


# Блоки, из которых нечего брать: меню, футер, cookie-баннеры, формы.
_JUNK_PARAGRAPH = re.compile(
    r"(cookie|политик\w+ конфиденциальн|все права защищен|©|обратн\w+ звонок|"
    r"оставьте заявку|перейти к содержимому|каталог товаров|версия для слабовидящих)",
    re.I,
)


def _first_paragraph(soup: BeautifulSoup) -> str:
    """Первый абзац, похожий на рассказ о компании, а не на элемент интерфейса."""
    for tag in soup.find_all(["p", "div", "section"], limit=400):
        # Берём только «листья»: у вложенного div текст всей страницы.
        if tag.find(["p", "div", "section"]):
            continue
        text = _clean(tag.get_text(" ", strip=True))
        if len(text) < 80 or len(text) > 700:
            continue
        if _JUNK_PARAGRAPH.search(text):
            continue
        if text.count("|") > 2 or text.count("·") > 2:  # хлебные крошки/меню
            continue
        return text[:400]
    return ""


def _extract_facts(soup: BeautifulSoup, url: str) -> list[Fact]:
    text = _clean(soup.get_text(" ", strip=True))[:12000]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    facts: list[Fact] = []

    for pattern, kind in FACT_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        phrase = _clean(m.group(0))
        # Предложение целиком читается лучше вырезки по символам, но на сайтах
        # половина текста — это блоки без точек, там предложение бесполезно
        # длинное. В таком случае оставляем саму найденную формулировку.
        host = _clean(next((s for s in sentences if phrase in s), ""))
        if 40 <= len(host) <= 220:
            snippet = host
        else:
            # Окно вокруг совпадения, обрезанное по границам слов: «с 2014 год»
            # само по себе ни о чём не говорит, нужен контекст.
            snippet = _snap_to_words(text, m.start(), m.end(), pad=90)
        if len(snippet) >= 40:
            facts.append(Fact(text=snippet, kind=kind, source_url=url))
    return facts


# Пункты меню и футера. Пунктуации между ними нет, поэтому по границе
# предложения их не отрезать — ищем по словам.
_NAV_WORDS = re.compile(
    r".*(?:обратная связь|о компании|контакты|доставка и оплата|доставка|"
    r"гарантия|корзина|личный кабинет|каталог|главная|вакансии|новости и акции)\s+",
    re.I | re.S,
)


def _snap_to_words(text: str, start: int, end: int, pad: int = 90) -> str:
    """Вырезка вокруг совпадения: без обрубленных слов и без хвоста меню."""
    left = text[max(0, start - pad):start]
    right = text[end:end + pad]

    # Предпочитаем начать с начала предложения, если оно попало в окно.
    sentence = re.search(r"[.!?]\s+(?=[А-ЯA-Z])", left)
    if sentence:
        left = left[sentence.end():]
    else:
        nav = _NAV_WORDS.match(left)
        if nav:
            left = left[nav.end():]
        elif " " in left:
            left = left[left.index(" ") + 1:]

    if " " in right:
        right = right[:right.rindex(" ")]
    return _clean(f"{left}{text[start:end]}{right}")


def collect(domain: str, max_pages: int = 5) -> CompanyFacts:
    """Обойти главную и страницы контактов, собрать почту, имена и факты."""
    domain = re.sub(r"^\w+://", "", (domain or "").strip()).split("/")[0]
    out = CompanyFacts(domain=domain)
    if not domain:
        return out

    base = f"https://{domain}"
    visited: set[str] = set()

    for path in CONTACT_PATHS:
        if len(out.pages_seen) >= max_pages:
            break
        url = urljoin(base, path) if path else base
        if url in visited:
            continue
        visited.add(url)

        html = fetch(url)
        if html is None and not out.pages_seen and not path:
            html = fetch(f"http://{domain}")  # сайт без https — ещё встречается
        if not html:
            continue

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        out.reachable = True
        out.pages_seen.append(url)

        if not out.title and soup.title:
            out.title = _clean(soup.title.get_text(" ", strip=True))[:200]

        if not out.description:
            for selector, attr in (
                ('meta[property="og:description"]', "content"),
                ('meta[name="description"]', "content"),
            ):
                tag = soup.select_one(selector)
                if tag and _clean(tag.get(attr, "")):
                    out.description = _clean(tag[attr])[:400]
                    out.description_source = url
                    break

        if not out.headline:
            h = soup.find(["h1", "h2"])
            if h:
                out.headline = _clean(h.get_text(" ", strip=True))[:200]

        if not out.lead_paragraph:
            out.lead_paragraph = _first_paragraph(soup)
            if out.lead_paragraph:
                out.lead_source = url

        for addr in _extract_emails(html, soup):
            if addr not in out.emails:
                out.emails.append(addr)
                out.email_sources[addr] = url

        for name in _extract_names(soup):
            if name not in out.contact_names:
                out.contact_names.append(name)

        for fact in _extract_facts(soup, url):
            if all(fact.kind != f.kind for f in out.facts):
                out.facts.append(fact)

    log.debug("%s: страниц %d, почт %d, фактов %d",
              domain, len(out.pages_seen), len(out.emails), len(out.facts))
    return out


def same_domain(email: str, domain: str) -> bool:
    host = urlparse(f"//{domain}").netloc or domain
    return email.partition("@")[2].endswith(host.replace("www.", ""))
