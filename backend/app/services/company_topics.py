"""начальные темы компании по основному ОКВЭД без обращения к модели"""

import re

from app.schemas.database import CompanyTagInput

OKVED_TOPICS = {
    "01": ("biz_agr",),
    "01.4": ("biz_liv",),
    "02": ("biz_forest",),
    "03": ("biz_aqua",),
    "06.1": ("biz_oil",),
    "06.2": ("biz_gas",),
    "10": ("biz_food",),
    "18": ("biz_print",),
    "20": ("biz_chem",),
    "22": ("biz_plast",),
    "25": ("biz_metal",),
    "25.11": ("biz_buildmat", "biz_metal"),
    "35": ("biz_energy",),
    "35.2": ("biz_gas",),
    "35.3": ("biz_heat",),
    "41": ("biz_construct",),
    "42": ("biz_construct", "biz_infra"),
    "43": ("biz_construct", "biz_repair"),
    "45.1": ("biz_retail",),
    "45.2": ("biz_carservice",),
    "45.3": ("biz_wholesale",),
    "46": ("biz_wholesale",),
    "47": ("biz_retail",),
    "47.91": ("biz_retail", "biz_ecom"),
    "49.4": ("biz_logistic", "biz_freight"),
    "52": ("biz_logistic",),
    "52.1": ("biz_logistic", "biz_warehouse"),
    "55": ("biz_hotel", "biz_tourism"),
    "56": ("biz_catering",),
    "60": ("biz_media",),
    "61": ("biz_telecom",),
    "62": ("biz_it",),
    "62.01": ("biz_it", "biz_software"),
    "63.11": ("biz_it", "biz_cloud", "biz_data"),
    "64.2": ("biz_govern",),
    "64.91": ("biz_leasing",),
    "64.99.11": ("biz_invest", "biz_stock"),
    "68": ("biz_realty",),
    "68.2": ("biz_realty", "biz_rent"),
    "68.32": ("biz_realty", "biz_rent"),
    "69.1": ("biz_legal",),
    "69.2": ("biz_account", "biz_audit"),
    "70.22": ("biz_consult",),
    "71": ("biz_arch",),
    "72": ("biz_science",),
    "73.1": ("biz_marketing",),
    "73.2": ("biz_research",),
    "77.4": ("biz_ip",),
    "80": ("biz_security",),
    "86": ("biz_health",),
    "90": ("biz_culture",),
    "93.1": ("biz_fitness",),
}


def operating_topics(company):
    """добавляет темы общих издержек и обязательств по известному виду деятельности"""
    industry = {tag.tag_id for tag in initial_company_topics(company)}
    topics = set()
    if industry & {"biz_freight", "biz_logistic"}:
        topics.update({"biz_oil", "biz_refine"})
    if industry & {"biz_it", "biz_software", "biz_cloud", "biz_data", "biz_health"}:
        topics.update({"biz_privacy", "biz_cyber"})
    if industry & {"biz_construct", "biz_infra", "biz_repair"}:
        topics.add("biz_buildmat")
    if industry & {"biz_wholesale", "biz_retail", "biz_catering"}:
        topics.add("biz_inflation")
    return {tag: 1.0 for tag in topics}


def initial_company_topics(company):
    """находит наиболее точное правило ОКВЭД, неизвестный код оставляет без тем

    вес 1,5 даёт отрасли приоритет над общими интересами должности
    это начальная настройка формулы, а не результат обучения
    """
    return [
        CompanyTagInput(tag_id=tag, origin="rule", base_weight=1.5)
        for tag in topics_for_okved(company.okved_code)
    ]


def topics_for_okved(code):
    """возвращает темы наиболее точного правила ОКВЭД"""
    code = (code or "").strip()
    if not re.fullmatch(r"[0-9]{2}(?:\.[0-9]{1,2}){0,2}", code):
        return []
    matches = [prefix for prefix in OKVED_TOPICS if code.startswith(prefix)]
    if not matches:
        return []
    prefix = max(matches, key=len)
    return list(OKVED_TOPICS[prefix])


def counterparty_topics(company):
    """считает косвенный интерес к отраслям контрагентов по долям платежей в выборке"""
    weights = {}
    for direction in ("incoming", "outgoing"):
        for code, share in company.profile_json.get(
            f"payment_{direction}_sectors", {}
        ).items():
            for tag in topics_for_okved(code):
                weights[tag] = min(0.25, weights.get(tag, 0) + share / 100 * 0.125)
    return weights
