"""Задача 3: цепочка писем.

Тексты лежат в data/task3_sequence.json, а не в коде: их правят руками, и
держать их рядом с логикой неудобно. Отсюда же рендер в Markdown (для сдачи),
в CSV (лист в Google Таблице) и подстановка персонализации из задачи 2 —
чтобы можно было глазами посмотреть готовое письмо под конкретную компанию,
а не шаблон с фигурными скобками.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

WORD_LIMIT = 120


@dataclass
class Email:
    step: int
    day: int
    goal: str
    subject: str
    body: str
    why: str

    @property
    def word_count(self) -> int:
        """Считаем слова так, как их посчитает проверяющий: подстановки —
        это одно слово, знаки препинания не в счёт."""
        text = re.sub(r"\{\{[^}]+\}\}", "X", self.body)
        return len(re.findall(r"[0-9A-Za-zА-Яа-яЁё][\w–-]*", text))

    @property
    def within_limit(self) -> bool:
        return self.word_count <= WORD_LIMIT


@dataclass
class Sequence:
    product: str
    icp: str
    variables: dict[str, str]
    personalization_fallback: str
    emails: list[Email]


def load(path: Path) -> Sequence:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Sequence(
        product=data["product"],
        icp=data["icp"],
        variables=data["variables"],
        personalization_fallback=data["personalization_fallback"],
        emails=[Email(**e) for e in data["emails"]],
    )


def render(body: str, company: str = "", name: str = "", personalization: str = "",
           sender: str = "", fallback: str = "") -> str:
    """Подставить значения. Пустая персонализация заменяется нейтральной
    фразой, иначе в письме остаётся дыра или, того хуже, скобки."""
    return (body
            .replace("{{персонализация}}", personalization.strip() or fallback)
            .replace("{{Имя}}", _greeting_name(name))
            .replace("{{Компания}}", company or "вашей командой")
            .replace("{{Отправитель}}", sender or "Никита"))


# В колонке «Контакт» может стоять прочерк или «отдел продаж»: имени компания
# не публикует. Подставлять это в приветствие нельзя — «Здравствуйте, —.»
# убивает письмо вернее, чем отсутствие имени.
_NOT_A_GREETING = {"", "—", "-", "не указано", "отдел продаж", "приемная", "приёмная"}


def _greeting_name(name: str) -> str:
    cleaned = (name or "").split("(")[0].strip()
    if cleaned.lower() in _NOT_A_GREETING:
        return "коллеги"
    return cleaned.split()[1] if len(cleaned.split()) >= 3 else cleaned


def to_markdown(seq: Sequence) -> str:
    lines = [
        "# Задача 3 — цепочка писем Polza Agency",
        "",
        f"**Что продаём:** {seq.product}",
        f"**Кому:** {seq.icp}",
        "",
        "**Переменные:**",
        "",
    ]
    lines += [f"- `{k}` — {v}" for k, v in seq.variables.items()]
    lines += [
        "",
        f"Если персонализация пустая (сайт не открылся или факта на нём нет), "
        f"подставляется нейтральная фраза: «{seq.personalization_fallback}» — "
        f"пустую переменную в письмо не выпускаем.",
        "",
    ]
    for e in seq.emails:
        when = "в день старта" if e.day == 0 else f"через {e.day} дн. после первого"
        lines += [
            f"## Письмо {e.step} — {e.goal}",
            "",
            f"*Отправка: {when}. Слов: {e.word_count} из {WORD_LIMIT}.*",
            "",
            f"**Тема:** {e.subject}",
            "",
            "```",
            e.body,
            "```",
            "",
            f"**Почему так:** {e.why}",
            "",
        ]
    return "\n".join(lines)


def to_csv(seq: Sequence, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Шаг", "День отправки", "Цель", "Тема", "Текст", "Слов", "Почему так"])
        for e in seq.emails:
            w.writerow([e.step, e.day, e.goal, e.subject, e.body, e.word_count, e.why])
    return path
