"""Задача 4: проверка чужой базы перед персонализацией.

В присланной таблице название компании, почта и сайт в части строк относятся
к разным компаниям. Персонализировать такую строку бессмысленно: факт будет
взят с чужого сайта и уедет чужому человеку. Поэтому сначала аудит, потом
обогащение.

Логика в три шага:
 1. Согласованность внутри строки — похож ли домен на название, совпадает ли
    домен почты с доменом сайта.
 2. Согласованность по таблице — не «уехал» ли домен в соседнюю строку,
    нет ли дублей домена.
 3. Подтверждение живым сайтом — встречается ли название компании на самом
    сайте. Это единственная проверка, которая отличает догадку от факта,
    поэтому она и решает итоговый статус строки.

Замечания (ролевой ящик, публичная почта) держим отдельно от ошибок: они есть
почти в каждой строке и, если смешать, реальные подмены в них тонут.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from .emailcheck import check as check_email
from .http_client import fetch
from .textnorm import (
    match_score,
    name_tokens,
    registrable_domain,
    translit_variants,
)

# Ниже этого совпадения считаем, что домен не про эту компанию.
MISMATCH_THRESHOLD = 0.55
# Выше — уверенное совпадение, годится как предложение исправления.
CONFIDENT_THRESHOLD = 0.8

OK = "ok"
CHECK = "проверить вручную"
BROKEN = "перепутано"


@dataclass
class RowAudit:
    row: int
    company: str
    email: str
    website: str
    site_score: float = 0.0
    email_score: float = 0.0
    email_matches_site: bool = False
    site_confirms_company: bool | None = None   # None = сайт не ответил
    site_evidence: str = ""
    suggested_domain: str = ""
    suggested_owner_row: int | None = None
    issues: list[str] = field(default_factory=list)   # ошибки данных
    notes: list[str] = field(default_factory=list)    # замечания к качеству
    domain_claimed_by_other: bool = False             # её домен «хочет» другая строка
    status: str = OK
    recommendation: str = ""

    @property
    def safe_to_personalize(self) -> bool:
        return self.status == OK


REQUIRED_COLUMNS = ("company", "email", "website")


def load_rows(path: Path) -> list[dict[str, str]]:
    """Прочитать входную базу, проверив заголовки.

    Без проверки файл с другими заголовками читается как набор пустых строк,
    и скрипт бодро сообщает, что база чистая. Для задачи, весь смысл которой
    в поиске ошибок, это худший из возможных отказов.
    """
    if not path.exists():
        raise SystemExit(f"Файл не найден: {path}")

    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(
                f"В файле {path.name} нет обязательных колонок: "
                f"{', '.join(missing)}. Найдены: "
                f"{', '.join(reader.fieldnames or ['(пусто)'])}"
            )
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def _site_mentions_company(website: str, company: str) -> tuple[bool | None, str]:
    """Ищем название компании на её же сайте. Возвращаем (найдено, цитата)."""
    html = None
    for url in (f"https://{website}", f"http://{website}"):
        html = fetch(url)
        if html:
            break
    if not html:
        return None, "сайт не ответил"

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    body_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)[:20000]).lower()
    haystack = " ".join(
        part for part in [
            soup.title.get_text(" ", strip=True) if soup.title else "",
            " ".join(m.get("content", "") or "" for m in soup.find_all("meta")),
            body_text,
        ] if part
    ).lower()
    haystack = re.sub(r"\s+", " ", haystack)

    for token in name_tokens(company):
        for variant in translit_variants(token):
            if len(variant) < 4:
                continue
            pos = haystack.find(variant)
            if pos >= 0:
                quote = haystack[max(0, pos - 45): pos + 55].strip()
                return True, f"на сайте есть «{variant}»: …{quote}…"

    # Сайт целиком на иероглифах: латинского написания названия там просто нет,
    # и отсутствие совпадения ничего не доказывает. Честнее сказать «не знаю»,
    # чем записать компанию в перепутанные (так mgwmachine.com = 铭文 Mingwen).
    # Долю считаем по видимому тексту: в meta-тегах у любого WordPress лежит
    # английская обвязка плагинов, из-за неё китайский сайт выглядит латинским.
    letters = [c for c in body_text if c.isalpha()]
    latin = sum(1 for c in letters if "a" <= c <= "z" or "а" <= c <= "я" or c == "ё")
    if letters and latin / len(letters) < 0.5:
        return None, "сайт не на латинице/кириллице — автоматически не сверить, нужна ручная проверка"

    return False, "название компании на сайте не встречается"


def _collect_domain_pool(rows: list[dict[str, str]]) -> list[str]:
    """Все домены таблицы: уехавший домен почти всегда лежит в соседней строке."""
    pool: list[str] = []
    for r in rows:
        for value in (r.get("website", ""), r.get("email", "").partition("@")[2]):
            rd = registrable_domain(value) if value else ""
            if rd and rd not in pool:
                pool.append(rd)
    return pool


def audit(rows: list[dict[str, str]], verify_online: bool = True) -> list[RowAudit]:
    check_mx = verify_online  # офлайн — значит и без DNS, иначе «офлайн» лукавит
    results: list[RowAudit] = []
    pool = _collect_domain_pool(rows)

    for idx, r in enumerate(rows, start=1):
        company = r.get("company", "")
        email = r.get("email", "")
        website = r.get("website", "")
        a = RowAudit(row=idx, company=company, email=email, website=website)

        email_domain = email.partition("@")[2]
        a.site_score = match_score(company, website) if website else 0.0
        a.email_score = match_score(company, email_domain) if email_domain else 0.0
        a.email_matches_site = bool(
            email_domain and website
            and registrable_domain(email_domain) == registrable_domain(website)
        )

        verdict = check_email(email, check_mx=check_mx)
        # Невалидный синтаксис / мёртвый домен — это ошибка данных,
        # ролевой ящик и публичная почта — замечание к качеству.
        for problem in verdict.problems:
            if "синтаксис" in problem or "MX" in problem or "одноразов" in problem:
                a.issues.append(problem)
            else:
                a.notes.append(problem)

        if website and a.site_score < MISMATCH_THRESHOLD:
            a.issues.append(
                f"сайт {website} не похож на домен «{company}» (совпадение {a.site_score})"
            )
        if email_domain and a.email_score < MISMATCH_THRESHOLD and not verdict.is_freemail:
            a.issues.append(
                f"домен почты {email_domain} не похож на «{company}» (совпадение {a.email_score})"
            )
        if email_domain and website and not a.email_matches_site and not verdict.is_freemail:
            msg = (f"домен почты ({registrable_domain(email_domain)}) "
                   f"не совпадает с доменом сайта ({registrable_domain(website)})")
            # Если оба домена похожи на название — это просто второй домен компании.
            if a.site_score >= CONFIDENT_THRESHOLD and a.email_score >= CONFIDENT_THRESHOLD:
                a.notes.append(msg + " — похоже на второй домен той же компании")
            else:
                a.issues.append(msg)

        best_domain, best_score = "", 0.0
        for domain in pool:
            score = match_score(company, domain)
            if score > best_score:
                best_domain, best_score = domain, score
        if best_domain and best_score >= CONFIDENT_THRESHOLD \
                and registrable_domain(website) != best_domain:
            a.suggested_domain = best_domain

        results.append(a)

    # Дубли сайтов: один домен на две компании — верный признак сдвига строк.
    seen: dict[str, list[int]] = {}
    for a in results:
        if a.website:
            seen.setdefault(registrable_domain(a.website), []).append(a.row)
    for domain, rows_with in seen.items():
        if len(rows_with) > 1:
            for a in results:
                if a.row in rows_with:
                    others = ", ".join(str(n) for n in rows_with if n != a.row)
                    a.issues.append(f"домен {domain} дублируется со строкой {others}")

    # Кто настоящий владелец предложенного домена
    for a in results:
        if not a.suggested_domain:
            continue
        for other in results:
            if other.row != a.row and registrable_domain(other.website) == a.suggested_domain:
                a.suggested_owner_row = other.row
        where = f" (сейчас он стоит в строке {a.suggested_owner_row})" if a.suggested_owner_row else ""
        a.issues.append(f"судя по названию, домен этой компании — {a.suggested_domain}{where}")

    # Обратная сторона: если на мой домен претендует другая строка, моя строка
    # тоже неверна — даже если её сайт не ответил и сверить название нечем.
    for a in results:
        claimants = [
            o.row for o in results
            if o.row != a.row and o.suggested_domain
            and o.suggested_domain == registrable_domain(a.website)
        ]
        if claimants:
            a.issues.append(
                f"домен {registrable_domain(a.website)} по названию принадлежит компании "
                f"из строки {', '.join(map(str, claimants))}, а не «{a.company}»"
            )
            a.domain_claimed_by_other = True

    if verify_online:
        for a in results:
            if a.website:
                a.site_confirms_company, a.site_evidence = _site_mentions_company(a.website, a.company)

    for a in results:
        _finalize(a)
    return results


def _finalize(a: RowAudit) -> None:
    """Итоговый статус. Живой сайт важнее любых эвристик по строкам."""
    if a.site_confirms_company is True:
        # Название нашлось на сайте — претензии к «непохожему» домену снимаем:
        # mgwmachine.com для Mingwen выглядит чужим, но сайт именно их.
        kept = [i for i in a.issues if "не похож на домен" not in i and "домен этой компании" not in i]
        moved = [i for i in a.issues if i not in kept]
        if moved:
            a.notes.append("домен не выводится из названия, но сайт подтверждает компанию")
        a.issues = kept

    if not a.issues:
        a.status = OK
        a.recommendation = "брать в персонализацию как есть"
    elif a.site_confirms_company is False or a.domain_claimed_by_other:
        a.status = BROKEN
        if a.suggested_domain:
            a.recommendation = f"не персонализировать; заменить сайт на {a.suggested_domain} и перепроверить"
        else:
            a.recommendation = "не персонализировать; найти настоящий сайт компании по названию"
    else:
        a.status = CHECK
        why = a.site_evidence or "сайт не ответил"
        a.recommendation = f"проверить вручную перед отправкой: {why}"

    if a.status == OK and a.notes:
        a.recommendation += "; " + a.notes[0]


def write_report(results: list[RowAudit], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "task4_audit.csv"
    md_path = out_dir / "task4_audit.md"

    confirm_label = {True: "да", False: "нет", None: "сверить не удалось"}

    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "№", "Компания", "Email", "Сайт", "Статус", "Что делать",
            "Совпадение сайт↔название", "Совпадение почта↔название",
            "Почта и сайт на одном домене", "Название есть на сайте",
            "Предполагаемый верный домен", "Домен уехал из строки",
            "Ошибки", "Замечания",
        ])
        for a in results:
            w.writerow([
                a.row, a.company, a.email, a.website, a.status, a.recommendation,
                a.site_score, a.email_score,
                "да" if a.email_matches_site else "нет",
                confirm_label[a.site_confirms_company] if a.site_confirms_company is not None
                else (a.site_evidence or "сайт не ответил"),
                a.suggested_domain, a.suggested_owner_row or "",
                "; ".join(a.issues), "; ".join(a.notes),
            ])

    broken = [a for a in results if a.status == BROKEN]
    check = [a for a in results if a.status == CHECK]
    ok = [a for a in results if a.status == OK]

    lines = [
        "# Задача 4 — аудит присланной базы",
        "",
        f"Строк: {len(results)}. Чистых: {len(ok)}. Перепутано: {len(broken)}. "
        f"Не удалось проверить: {len(check)}.",
        "",
        "Строки со статусом «перепутано» персонализировать нельзя: название, почта",
        "и сайт в них относятся к разным компаниям, поэтому факт будет взят с чужого",
        "сайта и уйдёт не тому адресату. Ниже — что именно не сходится.",
        "",
    ]
    for group, title in ((broken, "Перепутанные строки"), (check, "Требуют ручной проверки")):
        if not group:
            continue
        lines += [f"## {title}", ""]
        for a in group:
            lines.append(f"### {a.row}. {a.company}")
            lines.append(f"- в таблице: `{a.email}` / `{a.website}`")
            for issue in a.issues:
                lines.append(f"- {issue}")
            if a.site_evidence:
                lines.append(f"- проверка сайта: {a.site_evidence}")
            lines.append(f"- **что делать:** {a.recommendation}")
            lines.append("")

    if ok:
        lines += ["## Чистые строки", ""]
        for a in ok:
            note = f" — {a.notes[0]}" if a.notes else ""
            lines.append(f"- {a.row}. {a.company} (`{a.website}`){note}")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path
