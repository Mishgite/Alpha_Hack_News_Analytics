"""сопоставляет названия и коды городов с регионами общего справочника"""

import re
from functools import lru_cache

from .tag_catalog import load_catalog


def normalize_name(value):
    """убирает регистр, префикс города и различия в написании разделителей"""
    value = (value or "").casefold().replace("ё", "е")
    value = re.sub(r"^(?:город\s+|г\.\s*|г\s+)", "", value.strip())
    return " ".join(re.findall(r"[a-zа-я0-9]+", value))


def region_alias(value):
    """приводит область, край и республику к одному порядку слов для поиска"""
    words = normalize_name(value).split()
    replacements = {"обл": "область", "респ": "республика", "ао": "автономный округ"}
    words = " ".join(replacements.get(word, word) for word in words).split()
    return " ".join(sorted(words))


@lru_cache(maxsize=1)
def geography_catalog():
    """строит индексы без угадывания региона по цифрам в коде города"""
    catalog = load_catalog()
    regions, cities, names = {}, {}, {}
    for label, code in catalog["region"].items():
        english, russian = label.split(" / ", 1)
        names[code] = russian
        for alias in (code, english, russian):
            regions.setdefault(region_alias(alias), set()).add(code)
    for alias, code in {
        "Кемеровская область": "reg_42",
        "Кузбасс": "reg_42",
        "Чувашская Республика-Чувашия": "reg_21",
        "Чувашия": "reg_21",
        "Якутия": "reg_14",
        "Республика Саха (Якутия)": "reg_14",
        "ХМАО": "reg_86",
        "Ханты-Мансийский автономный округ": "reg_86",
        "ЯНАО": "reg_89",
    }.items():
        if code in names:
            regions.setdefault(region_alias(alias), set()).add(code)
    for label, code in catalog["city"].items():
        english, russian = label.split(" / ", 1)
        match = re.fullmatch(r"(.+) \((.+)\)", russian)
        if not match:
            continue
        city, region = match.groups()
        matches = regions.get(region_alias(region), set())
        if len(matches) != 1:
            continue
        english_city = english.split(" (", 1)[0]
        for alias in (code, city, russian, english_city, english, label):
            cities.setdefault(normalize_name(alias), set()).update(matches)
    return regions, cities, names


def resolve_region(value):
    """возвращает код только для однозначно распознанного названия региона"""
    matches = geography_catalog()[0].get(region_alias(value), set())
    return next(iter(matches)) if len(matches) == 1 else None


def city_region(value, region=None):
    """определяет регион города, для одноимённых городов требует уточнение региона"""
    matches = geography_catalog()[1].get(normalize_name(value), set())
    if region is not None:
        return region if region in matches else None
    return next(iter(matches)) if len(matches) == 1 else None


def region_codes(values):
    """нормализует географические названия и коды, неизвестные значения пропускает"""
    return sorted(
        {
            code
            for value in values or []
            if (code := resolve_region(value) or city_region(value))
        }
    )


def region_names(codes):
    """возвращает названия регионов для объяснения результата ранжирования"""
    names = geography_catalog()[2]
    return ", ".join(names[code] for code in codes if code in names)


def company_geography(company):
    """разделяет регистрацию и деятельность, текстовый адрес использует только для регистрации"""
    explicit_region = resolve_region(company.registered_region_code)
    registered = explicit_region or resolve_region(company.region)
    from_city = city_region(company.city)
    if not registered:
        registered = from_city
    elif from_city and from_city != registered and not explicit_region:
        registered = None
    operating = region_codes(company.operating_region_codes)
    country = company.country_code.strip().upper() if company.country_code else None
    if country is None and registered:
        # справочник reg_* содержит субъекты России, регионы деятельности из регистрации не выводятся
        country = "RU"
    return (
        country,
        registered,
        operating if company.operating_region_codes is not None else None,
    )
