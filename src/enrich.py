"""Сборка финальной таблицы: аудит → факты с сайта → колонка «Персонализация».

Порядок принципиальный. Персонализируем только те строки, которые прошли
аудит: для перепутанной строки любой «факт» будет взят с сайта чужой компании,
а это хуже пустой ячейки — такое письмо выдаёт себя с первой строки.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .audit import RowAudit
from .personalize import build
from .site_facts import collect

COLUMNS = [
    "Компания", "Email", "Сайт", "Статус аудита", "Персонализация",
    "Источник факта", "Уверенность", "Провайдер", "Контактное лицо с сайта",
    "Почта с сайта", "Комментарий",
]


def enrich(results: list[RowAudit], provider: str = "auto") -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for a in results:
        row = {
            "Компания": a.company,
            "Email": a.email,
            "Сайт": a.website,
            "Статус аудита": a.status,
            "Персонализация": "",
            "Источник факта": "",
            "Уверенность": "",
            "Провайдер": "",
            "Контактное лицо с сайта": "",
            "Почта с сайта": "",
            "Комментарий": a.recommendation,
        }

        if not a.safe_to_personalize:
            row["Комментарий"] = f"не персонализировано: {a.recommendation}"
            rows.append(row)
            continue

        facts = collect(a.website)
        p = build(a.company, facts, provider=provider)

        row["Персонализация"] = p.text
        row["Источник факта"] = p.source_url
        row["Уверенность"] = p.confidence
        row["Провайдер"] = p.provider
        row["Контактное лицо с сайта"] = "; ".join(facts.contact_names)
        row["Почта с сайта"] = "; ".join(facts.emails[:3])

        if not p.usable:
            row["Комментарий"] = (
                "сайт открылся, но пригодного факта на нём нет — "
                "в письме использовать нейтральный вариант без {{персонализация}}"
            )
        rows.append(row)

    return rows


def write_csv(rows: list[dict[str, str]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path
