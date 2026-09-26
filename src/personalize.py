"""Задача 2: колонка «Персонализация».

Провайдер выбирается флагом, интерфейс один. По умолчанию работает
`extractive` — он не требует никаких ключей и ничего не сочиняет: берёт
формулировки с сайта компании и складывает их в одно-два предложения,
сохраняя ссылку на страницу-источник.

`anthropic` включается, если в окружении есть ANTHROPIC_API_KEY. Он получает
ровно те же вытащенные со страницы куски и только переписывает их живым
языком — придумывать ему нечего, факты приходят готовыми. Это важно: если
отдать модели одно название компании, она начнёт галлюцинировать «ваш опыт
на рынке с 2009 года», и такая персонализация хуже, чем никакой.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from .site_facts import CompanyFacts

log = logging.getLogger(__name__)

MAX_SENTENCES = 2
# Маркетинговая вода: если предложение состоит только из неё, оно не факт.
FLUFF = re.compile(
    r"^(индивидуальн\w+ подход|высок\w+ качеств\w+|лучш\w+ цен\w+|"
    r"широк\w+ ассортимент|гибк\w+ услови\w+|команда профессионалов|"
    r"приемлем\w+ цен\w+|обширн\w+ сфера)",
    re.I,
)

# Куски интерфейса и SEO, которые выглядят как текст, но фактом не являются:
# лента новостей с датами, кнопки «Подробнее», витринные строки магазина.
PAGE_JUNK = re.compile(
    r"(\d{1,2}\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|"
    r"ноябр|декабр)\w*\s+подробнее|подробнее\s*$|читать далее|"
    r"^купить\s|интернет-магазин\w*\s+бренда|доставка по (росси|москв)|"
    r"[✔✓☑]|добавить в корзину|акции и скидки|контактные данные компании)",
    re.I,
)


@dataclass
class Personalization:
    text: str
    source_url: str
    confidence: str       # high / medium / none
    provider: str

    @property
    def usable(self) -> bool:
        return bool(self.text) and self.confidence != "none"


def _first_sentences(text: str, limit: int = MAX_SENTENCES) -> str:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    picked = [p for p in parts
              if len(p) > 25 and not FLUFF.match(p) and not PAGE_JUNK.search(p)][:limit]
    return " ".join(picked).strip()


def _extractive(company: str, facts: CompanyFacts) -> Personalization:
    if not facts.reachable:
        return Personalization("", "", "none", "extractive")

    # Приоритет — конкретике с цифрами, она всегда сильнее описания.
    if facts.facts:
        fact = facts.facts[0]
        lead = _first_sentences(facts.description, 1)
        text = f"{fact.text.rstrip('.')}."
        if lead and _is_readable(lead):
            text = f"{lead.rstrip('.')}. {text}"
        if _is_readable(text):
            return Personalization(_trim(text), fact.source_url, "high", "extractive")

    # Дальше — по убыванию надёжности: meta-описание, абзац «о компании»,
    # заголовок. Title берём последним: у половины сайтов это SEO-ключи.
    for body, source, confidence in (
        (facts.description, facts.description_source, "medium"),
        (facts.lead_paragraph, facts.lead_source, "medium"),
        (facts.headline, facts.pages_seen[0] if facts.pages_seen else "", "low"),
        (facts.title, facts.pages_seen[0] if facts.pages_seen else "", "low"),
    ):
        text = _first_sentences(body) or (_clean_short(body) if confidence == "low" else "")
        if text and _is_readable(text):
            return Personalization(_trim(text), source, confidence, "extractive")

    return Personalization("", facts.pages_seen[0] if facts.pages_seen else "",
                           "none", "extractive")


def _clean_short(text: str) -> str:
    """Заголовок — не предложение, но если он содержательный, он лучше пустоты."""
    text = re.sub(r"\s+", " ", (text or "")).strip(" |-–—")
    return text if 20 <= len(text) <= 200 and not FLUFF.match(text) else ""


def _is_readable(text: str) -> bool:
    """Отсечь то, что технически «текст», но в письмо не годится.

    Два реальных случая из прогона: китайское меню сайта (адресату на русском
    оно ничего не скажет) и перечисление ключевиков через запятую — такая
    «персонализация» сразу выдаёт, что её собирал скрипт.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    readable = sum(1 for c in letters if "a" <= c.lower() <= "z" or "а" <= c.lower() <= "я")
    if readable / len(letters) < 0.8:
        return False

    segments = [s.strip() for s in re.split(r"[,;·|/]", text) if s.strip()]
    if len(segments) >= 4 and sum(len(s) for s in segments) / len(segments) < 22:
        return False

    if PAGE_JUNK.search(text):
        return False

    # Телефон посреди «факта» означает, что зацепили блок контактов, а не текст.
    if re.search(r"\+7\s*\(?\d{3}", text):
        return False
    return True


def _trim(text: str, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:—-") + "…"


def _anthropic(company: str, facts: CompanyFacts) -> Personalization:
    """Переписать вытащенные факты живым языком. Без ключа — не вызывается."""
    import anthropic  # импорт внутри: без ключа зависимость не нужна

    base = _extractive(company, facts)
    if not base.usable:
        return base

    client = anthropic.Anthropic()
    prompt = (
        "Ты пишешь одну строку персонализации для холодного B2B-письма.\n"
        f"Компания: {company}\n"
        f"Дословно с её сайта: {base.text}\n\n"
        "Перепиши это в 1–2 предложения на русском так, будто ты правда "
        "посмотрел их сайт: конкретно, без лести и без слов «ваша динамично "
        "развивающаяся компания». Запрещено добавлять любые факты, которых нет "
        "в тексте выше. Верни только сам текст."
    )
    try:
        resp = client.messages.create(
            model="claude-opus-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _trim(resp.content[0].text.strip())
    except Exception as exc:  # сеть, лимиты, отсутствие баланса
        log.warning("anthropic упал (%s), откатываюсь на extractive", exc)
        return base

    return Personalization(text, base.source_url, base.confidence, "anthropic")


PROVIDERS = {"extractive": _extractive, "anthropic": _anthropic}


def build(company: str, facts: CompanyFacts, provider: str = "auto") -> Personalization:
    if provider == "auto":
        provider = "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "extractive"
    if provider not in PROVIDERS:
        raise ValueError(f"неизвестный провайдер: {provider}")
    return PROVIDERS[provider](company, facts)
