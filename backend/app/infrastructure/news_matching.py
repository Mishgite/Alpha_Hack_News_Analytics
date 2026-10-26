"""сравнивает публикации локально, не обращаясь к модели или внешним сервисам"""

import re
from functools import lru_cache

VERSION = "local-events-v1"
WINDOW_HOURS = 48
MAX_MEMBERS = 12
STOP = {
    "и",
    "в",
    "во",
    "на",
    "по",
    "с",
    "со",
    "к",
    "ко",
    "о",
    "об",
    "от",
    "до",
    "из",
    "за",
    "для",
    "при",
    "у",
    "а",
    "но",
    "что",
    "как",
    "это",
    "этот",
    "эта",
    "эти",
    "его",
    "ее",
    "их",
    "мы",
    "вы",
    "они",
    "он",
    "она",
    "уже",
    "также",
    "более",
    "менее",
    "после",
    "перед",
    "между",
    "через",
    "сегодня",
    "вчера",
    "завтра",
    "сообщил",
    "сообщает",
    "заявили",
    "стало",
    "будет",
    "будут",
    "был",
    "была",
    "были",
    "который",
    "которая",
    "которые",
    "года",
    "году",
    "год",
    "рублей",
    "рубль",
    "млн",
    "млрд",
    "тыс",
    "процентов",
    "процент",
    "россии",
    "российский",
    "российская",
    "российские",
    "тасс",
    "интерфакс",
    "риа",
    "новости",
    "компания",
    "компании",
    "банк",
    "банки",
}
STOP.update({"the", "a", "an", "of", "in", "on", "for", "and", "to", "is"})
ALIASES = ((r"\b(?:банк\s+россии|центробанк|цб\s*рф|цб)\b", "центробанк"),)


def normalize(text):
    """убирает различия регистра, буквы ё и распространённых названий центрального банка"""
    text = text.casefold().replace("ё", "е")
    for pattern, replacement in ALIASES:
        text = re.sub(pattern, replacement, text)
    return text


def stem(word):
    """сближает русские словоформы по основе, числа и латинские названия оставляет целиком"""
    return word[:5] if re.fullmatch(r"[а-я]{6,}", word) else word


def words(text):
    """выделяет значимые слова без служебных слов и коротких частиц"""
    return {
        stem(w)
        for w in re.findall(r"[a-zа-я]+", normalize(text))
        if len(w) > 2 and w not in STOP
    }


def dice(left, right):
    """считает долю общей лексики двух текстов, пустые тексты не считает совпадением"""
    return 2 * len(left & right) / (len(left) + len(right)) if left and right else 0.0


@lru_cache(maxsize=1024)
def signature(title, lead):
    """сохраняет слова, названия, числа, отрицания и направление действия для повторных сравнений"""
    normalized = normalize(title + " " + lead[:400])
    names = {
        stem(w.casefold().replace("ё", "е"))
        for w in re.findall(r"\b[A-ZА-ЯЁ][a-zа-яёA-ZА-ЯЁ]{2,}\b", title)
        if w.casefold().replace("ё", "е") not in STOP
        and not re.match(
            r"(?:Откр|Закр|Повы|Сниз|Сохр|Выро|Упал|План|Увел|Сокр|Одоб|Откл|Нач|Запу|Постр|Реш|Ста|Про|Цен)",
            w,
        )
    }
    if "центробанк" in normalize(title):
        names -= {"росси", "банк", "центр", "рф"}
        names.add("центробанк")
    numbers = frozenset(
        number.replace(",", ".") + ":" + ("%" if unit.startswith("процент") else unit)
        for number, unit in re.findall(
            r"(\d+(?:[.,]\d+)?)\s*(%|процент\w*|млрд|млн|тыс\.?|январ\w*|феврал\w*|март\w*|апрел\w*|ма[йяе]|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*|)",
            normalized,
        )
    )
    places = frozenset(
        stem(place.casefold().replace("ё", "е"))
        for place in re.findall(
            r"\b(?:[Вв]|[Ии]з|[Пп]од|[Оо]коло|[Нн]а территории)\s+([А-ЯЁ][а-яё]{3,})",
            title + " " + lead[:400],
        )
    )
    actions = set()
    for label, pattern in (
        ("up", r"\b(?:повы[сш]|увелич|вырос|рост)"),
        ("down", r"\b(?:сни[зж]|сокра[тщ]|упал|падени)"),
        ("hold", r"\b(?:сохран|оставил|неизмен)"),
        ("plan", r"\b(?:планир|намерен|построит|откроет|запустит)"),
        ("opened", r"\b(?:открыл|открыт|запустил|запущен)"),
        ("closed", r"\b(?:закрыл|закрыт|остановил|приостанов)"),
    ):
        if re.search(pattern, normalize(title)):
            actions.add(label)
    negated = bool(re.search(r"\b(?:не|нет|опроверг\w*|отрица\w*)\b", normalized))
    return (
        words(title),
        words(lead),
        frozenset(names),
        numbers,
        frozenset(actions),
        negated,
        places,
    )


def same_event(left_title, left_text, right_title, right_text):
    """объединяет только близкие пересказы без расхождений в названиях, числах и действии"""
    a = signature(left_title, left_text[:4000])
    b = signature(right_title, right_text[:4000])
    if min(len(a[0]), len(b[0])) < 4 or min(len(a[1]), len(b[1])) < 10:
        return False
    if a[2] != b[2] or not a[2] or a[3:] != b[3:]:
        return False
    title_score, body_score = dice(a[0], b[0]), dice(a[1], b[1])
    return (title_score >= 0.85 and body_score >= 0.55) or (
        title_score >= 0.65 and body_score >= 0.8
    )
