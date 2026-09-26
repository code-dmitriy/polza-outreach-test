"""Точка входа. `python -m src.cli <команда> --help`"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cmd_audit(args: argparse.Namespace) -> int:
    from .audit import audit, load_rows, write_report

    rows = load_rows(Path(args.input))
    results = audit(rows, verify_online=not args.offline)
    csv_path, md_path = write_report(results, Path(args.out))

    from .audit import BROKEN, CHECK, OK

    counts = {status: sum(1 for a in results if a.status == status) for status in (OK, BROKEN, CHECK)}
    print(f"Строк: {len(results)} | чистых: {counts[OK]} | перепутано: {counts[BROKEN]} "
          f"| не проверено: {counts[CHECK]}\n")
    for a in results:
        if a.status == OK:
            continue
        print(f"  [{a.row:>2}] {a.company} — {a.status}")
        for issue in a.issues:
            print(f"        · {issue}")
        print(f"        → {a.recommendation}")
    print(f"\nОтчёт: {md_path}\nТаблица: {csv_path}")
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    from .audit import OK, audit, load_rows
    from .enrich import enrich, write_csv

    rows = load_rows(Path(args.input))
    results = audit(rows, verify_online=not args.offline)
    enriched = enrich(results, provider=args.provider)
    out_path = write_csv(enriched, Path(args.out) / "task4_personalized.csv")

    filled = sum(1 for r in enriched if r["Персонализация"])
    skipped = sum(1 for a in results if a.status != OK)
    print(f"Строк: {len(enriched)} | персонализировано: {filled} | "
          f"пропущено по аудиту: {skipped}\n")
    for r in enriched:
        mark = "+" if r["Персонализация"] else "-"
        text = r["Персонализация"] or r["Комментарий"]
        print(f" {mark} {r['Компания'][:28]:30} {text[:90]}")
    print(f"\nТаблица: {out_path}")
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    from .collect import build_lead, to_rows, write_csv
    from .sources import wikiprom

    print(f"Собираю кандидатов из справочника (цель: {args.limit})…")
    companies = wikiprom.collect(limit=args.candidates, per_category=args.per_category)
    print(f"Компаний с сайтом и адресом в РФ: {len(companies)}\n")

    leads = []
    for i, company in enumerate(companies, start=1):
        if sum(1 for lead in leads if lead.is_complete) >= args.limit:
            break
        lead = build_lead(company, provider=args.provider, check_mx=not args.no_mx)
        leads.append(lead)
        mark = "+" if lead.is_complete else "·"
        print(f" {mark} [{i:>3}] {company.name[:34]:36} {lead.email[:30]:32} "
              f"{(lead.notes[0] if lead.notes else '')[:34]}")

    rows = to_rows(leads)
    out_path = write_csv(rows, Path(args.out) / "task1_base.csv")

    complete = sum(1 for lead in leads if lead.is_complete)
    with_email = sum(1 for lead in leads if lead.email)
    print(f"\nОбработано компаний: {len(leads)}")
    print(f"  с найденной почтой:        {with_email}")
    print(f"  полностью готовых строк:   {complete}")
    print(f"\nТаблица: {out_path}")
    return 0 if complete >= args.limit else 1


def cmd_emails(args: argparse.Namespace) -> int:
    from .sequence import WORD_LIMIT, load, render, to_csv, to_markdown

    seq = load(Path(args.input))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "task3_emails.md").write_text(to_markdown(seq), encoding="utf-8")
    csv_path = to_csv(seq, out_dir / "task3_emails.csv")

    over = [e for e in seq.emails if not e.within_limit]
    for e in seq.emails:
        mark = "ok " if e.within_limit else "МНОГО"
        print(f"  письмо {e.step}: {e.word_count:>3} слов ({mark}) — {e.subject}")

    if args.preview:
        print("\nПревью письма 1 с реальной персонализацией:\n")
        print(render(seq.emails[0].body, company="Искролайн", name="Иван",
                     personalization="Российский производитель эмиссионных спектрометров.",
                     fallback=seq.personalization_fallback))

    print(f"\nТексты: {out_dir / 'task3_emails.md'}\nТаблица: {csv_path}")
    if over:
        print(f"\nПревышен лимит {WORD_LIMIT} слов в письмах: "
              f"{', '.join(str(e.step) for e in over)}")
        return 1
    return 0


def cmd_hh_check(args: argparse.Namespace) -> int:
    """Быстрая проверка, что токен hh.ru подхватился и API отвечает."""
    from . import config
    from .http_client import fetch_json

    if not config.hh_token():
        print("HH_TOKEN не найден.")
        print("Скопируй .env.example в .env и вставь токен с https://dev.hh.ru/admin")
        return 1

    print(f"HH_TOKEN найден (длина {len(config.hh_token())} символов). Пробую API…")
    data = fetch_json("https://api.hh.ru/vacancies",
                      {"text": "менеджер по продажам", "area": 113, "per_page": 3},
                      use_cache=False)
    if not data:
        print("API не ответил или отклонил токен. Проверь, что приложение активно "
              "и токен скопирован целиком.")
        return 1

    print(f"Работает. Вакансий по запросу: {data.get('found', 0)}")
    for item in data.get("items", [])[:3]:
        employer = (item.get("employer") or {}).get("name", "?")
        print(f"  · {employer} — {item.get('name', '')[:60]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="polza", description="Тестовое задание Polza Agency")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="Задача 4: проверить базу на перепутанные строки")
    p_audit.add_argument("--input", default=str(ROOT / "data" / "task4_input.csv"))
    p_audit.add_argument("--out", default=str(ROOT / "out"))
    p_audit.add_argument("--offline", action="store_true", help="не ходить на сайты компаний")
    p_audit.set_defaults(func=cmd_audit)

    p_enrich = sub.add_parser("enrich", help="Задача 2/4: собрать факты с сайтов и заполнить персонализацию")
    p_enrich.add_argument("--input", default=str(ROOT / "data" / "task4_input.csv"))
    p_enrich.add_argument("--out", default=str(ROOT / "out"))
    p_enrich.add_argument("--offline", action="store_true")
    p_enrich.add_argument("--provider", default="auto",
                          choices=["auto", "extractive", "anthropic"],
                          help="auto = anthropic при наличии ANTHROPIC_API_KEY, иначе extractive")
    p_enrich.set_defaults(func=cmd_enrich)

    p_collect = sub.add_parser("collect", help="Задача 1: собрать базу B2B-компаний с почтами")
    p_collect.add_argument("--limit", type=int, default=50, help="сколько готовых строк нужно")
    p_collect.add_argument("--candidates", type=int, default=140,
                           help="сколько компаний взять из справочника (часть отсеется)")
    p_collect.add_argument("--per-category", type=int, default=6,
                           help="максимум компаний из одной категории — для разнообразия базы")
    p_collect.add_argument("--out", default=str(ROOT / "out"))
    p_collect.add_argument("--provider", default="auto",
                           choices=["auto", "extractive", "anthropic"])
    p_collect.add_argument("--no-mx", action="store_true", help="пропустить проверку MX")
    p_collect.set_defaults(func=cmd_collect)

    p_emails = sub.add_parser("emails", help="Задача 3: собрать цепочку писем и проверить лимит слов")
    p_emails.add_argument("--input", default=str(ROOT / "data" / "task3_sequence.json"))
    p_emails.add_argument("--out", default=str(ROOT / "out"))
    p_emails.add_argument("--preview", action="store_true", help="показать письмо 1 с подстановками")
    p_emails.set_defaults(func=cmd_emails)

    p_hh = sub.add_parser("hh-check", help="Проверить токен hh.ru")
    p_hh.set_defaults(func=cmd_hh_check)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
