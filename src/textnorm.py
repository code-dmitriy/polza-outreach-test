"""Нормализация названий компаний и доменов + оценка «это одна и та же сущность?».

Нужна в двух местах:
  * задача 4 — понять, что в строке название, почта и сайт не про одну компанию;
  * задача 1/2 — склеить спарсенную компанию с найденным доменом.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Транслитерация по ГОСТ-подобной схеме: именно так домены пишут в рунете
# (ункомтех -> uncomtech, техносфера -> technosphera), поэтому даём несколько
# вариантов на неоднозначные буквы и сравниваем с доменом по лучшему из них.
_TRANSLIT = {
    "а": ["a"], "б": ["b"], "в": ["v"], "г": ["g"], "д": ["d"], "е": ["e"],
    "ё": ["e", "yo"], "ж": ["zh"], "з": ["z"], "и": ["i"], "й": ["y", "i"],
    "к": ["k", "c"], "л": ["l"], "м": ["m"], "н": ["n"], "о": ["o"],
    "п": ["p"], "р": ["r"], "с": ["s"], "т": ["t"], "у": ["u"], "ф": ["f"],
    "х": ["h", "kh"], "ц": ["ts", "c"], "ч": ["ch"], "ш": ["sh"], "щ": ["sch"],
    "ъ": [""], "ы": ["y"], "ь": [""], "э": ["e"], "ю": ["yu", "u"], "я": ["ya", "a"],
}

# Организационно-правовые формы и слова-пустышки: они есть у всех и для
# сопоставления с доменом бесполезны.
_STOPWORDS = {
    # RU
    "ооо", "оао", "зао", "пао", "ао", "ип", "тд", "тк", "нпо", "нпп", "пк",
    "гк", "риц", "завод", "группа", "компания", "торговый", "дом",
    # EN / общие
    "co", "ltd", "llc", "inc", "corp", "gmbh", "plc", "limited", "company",
    "group", "holding", "trading", "international", "intl",
    # отраслевой шум из этой конкретной базы
    "machinery", "machine", "machines", "technologies", "technology", "tech",
    "equipment", "precision", "science", "industrial", "industry", "tool",
    "tools", "cnc", "intelligent", "heavy", "solutions", "systems", "works",
}

# Домены многоуровневых зон: для них «ядро» домена надо брать на уровень левее.
_MULTI_TLD = {
    "com.cn", "com.br", "co.uk", "co.jp", "com.tr", "com.au", "com.hk",
    "co.kr", "com.tw", "com.sg", "net.cn", "org.cn",
}


def translit_variants(word: str) -> list[str]:
    """Все разумные латинские написания кириллического слова (до 32 штук)."""
    if not re.search(r"[а-яё]", word):
        return [word]
    variants = [""]
    for ch in word:
        options = _TRANSLIT.get(ch, [ch])
        if len(variants) * len(options) > 32:  # не взрываем комбинаторику
            options = options[:1]
        variants = [prefix + opt for prefix in variants for opt in options]
    return list(dict.fromkeys(variants))


def name_tokens(company: str) -> list[str]:
    """Значимые слова названия в нижнем регистре, без правовых форм и шума."""
    raw = re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", company.lower())
    tokens = [t for t in raw if t and t not in _STOPWORDS and len(t) > 1]
    # Если после чистки ничего не осталось (например, компания называется
    # просто «HNC»), возвращаем исходные слова — лучше так, чем пусто.
    return tokens or [t for t in raw if t]


def domain_core(domain: str) -> str:
    """Опознаваемая часть домена: mgwmachine.com -> mgwmachine, a.co.uk -> a."""
    host = domain.strip().lower()
    host = re.sub(r"^\w+://", "", host).split("/")[0].split(":")[0]
    host = re.sub(r"^www\.", "", host)
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_TLD:
        core = parts[-3]
    elif len(parts) >= 2:
        core = parts[-2]
    else:
        core = host
    return re.sub(r"[^a-z0-9]", "", core)


def registrable_domain(domain: str) -> str:
    """Домен второго (или третьего для com.cn) уровня — для сравнения почты и сайта."""
    host = re.sub(r"^\w+://", "", domain.strip().lower()).split("/")[0].split(":")[0]
    host = re.sub(r"^www\.", "", host)
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_TLD:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def canon(word: str) -> str:
    """Свести написание к «скелету», чтобы сравнивать транслит с доменом.

    Одно и то же слово в домене и в транслите пишут по-разному:
    ункомтех -> unkomteh, а домен uncomtech; техносфера -> tehnosfera,
    а домен technosphera. Приводим обе стороны к общему виду и сравниваем.
    """
    s = re.sub(r"[^a-z0-9]", "", word.lower())
    # Порядок важен: диграфы до одиночных букв.
    for src, dst in (("sch", "s"), ("ph", "f"), ("kh", "h"), ("ch", "h"),
                     ("ck", "k"), ("ts", "c"), ("q", "k"), ("x", "ks"),
                     ("c", "k"), ("y", "i"), ("w", "v")):
        s = s.replace(src, dst)
    return re.sub(r"(.)\1+", r"\1", s)  # удвоенные буквы схлопываем


def _acronyms(tokens: list[str]) -> set[str]:
    """HNC для 'Hua Nan Cnc', mgw для 'Ming Wen ...' — частый приём в доменах."""
    out = set()
    if len(tokens) >= 2:
        out.add("".join(t[0] for t in tokens))
    if tokens:
        out.add("".join(t[:2] for t in tokens[:3]))
        out.add("".join(t[:3] for t in tokens[:2]))
    return {a for a in out if len(a) >= 2}


def match_score(company: str, domain: str) -> float:
    """0.0–1.0: насколько домен похож на домен именно этой компании.

    Не бинарно намеренно — в отчёте задачи 4 полезно видеть «почти совпало»
    отдельно от «совсем мимо».
    """
    core = domain_core(domain)
    if not core:
        return 0.0
    core_c = canon(core)

    tokens = name_tokens(company)
    # Для каждого слова названия — его латинские варианты.
    variants: list[list[str]] = [translit_variants(t) for t in tokens]

    best = 0.0
    for token_variants in variants:
        for v in token_variants:
            if len(v) < 3:
                continue
            for a, b in ((v, core), (canon(v), core_c)):
                if a == b:
                    return 1.0
                if b.startswith(a) or b.endswith(a):
                    best = max(best, 0.9)
                elif a in b:
                    best = max(best, 0.8)
                else:
                    best = max(best, SequenceMatcher(None, a, b).ratio() * 0.75)

    # Склейка всех слов: fengyiyinhu vs fengyitool
    for combo in _joined_variants(variants):
        for a, b in ((combo, core), (canon(combo), core_c)):
            if a == b:
                return 1.0
            if len(a) >= 4 and (b.startswith(a) or a.startswith(b)):
                best = max(best, 0.85)
            best = max(best, SequenceMatcher(None, a, b).ratio() * 0.8)

    # Аббревиатуры
    for acr in _acronyms([v[0] for v in variants]):
        if acr == core:
            best = max(best, 0.9)
        elif core.startswith(acr) and len(acr) >= 3:
            best = max(best, 0.75)

    return round(min(best, 1.0), 3)


def _joined_variants(variants: list[list[str]], limit: int = 8) -> list[str]:
    """Склеенные написания названия целиком, не более `limit` комбинаций."""
    combos = [""]
    for token_variants in variants:
        combos = [c + v for c in combos for v in token_variants[:2]]
        if len(combos) > limit:
            combos = combos[:limit]
    return [c for c in combos if c]
