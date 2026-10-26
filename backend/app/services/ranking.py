"""ранжирование по темам, свежести и совпадению географии до обучения модели"""

from app.schemas.ranking import RankedNews, RankingRequest, RankingResult

from .geography import city_region, region_codes, region_names, resolve_region

RANKING_VERSION = "formula-v4-counterparties"


def geography_match(profile, geography):
    """сравнивает регионы события с деятельностью компании, регистрацию учитывает слабее"""
    country = profile.country_code
    news_country = geography.country_code
    if country and news_country and country.upper() != news_country:
        return 0.0, "У новости и компании разные страны"
    if geography.nationwide is True:
        if country and news_country:
            return 1.0, "Новость относится ко всей стране компании"
        return (
            None,
            "Для сравнения общенациональной новости не указана страна компании или события",
        )
    regions = set(region_codes(geography.region_codes))
    regions.update(code for city in geography.city_codes if (code := city_region(city)))
    if not regions:
        return None, "Регион события неизвестен, география не меняет балл"
    operating = set(region_codes(profile.operating_region_codes))
    registered = resolve_region(profile.registered_region_code)
    if operating:
        matched = sorted(operating & regions)
        if matched:
            return 1.0, "Совпали регионы деятельности: " + region_names(matched)
        return 0.0, "Регион события не совпал с указанными регионами деятельности"
    if registered:
        if registered in regions:
            return 0.5, "Совпал регион регистрации: " + region_names(
                [registered]
            ) + "; регионы деятельности неизвестны"
        return (
            0.0,
            "Регион события не совпал с регистрацией; регионы деятельности неизвестны",
        )
    return None, "География компании неизвестна, география не меняет балл"


def rank_news(request: RankingRequest) -> RankingResult:
    """отбирает тематические новости и учитывает деловую значимость, масштаб и свежесть

    паттерн Strategy: FeedService получает функцию без зависимости от алгоритма
    локальному событию нужны отрасль компании или явно выбранный интерес
    свежесть меняет порядок подходящих новостей и не создаёт релевантность сама
    """
    items = []
    profile = request.profile
    direct_topics = set(profile.company_tag_ids) | set(profile.personal_tag_ids)
    for candidate in request.candidates:
        features = candidate.features
        signals = {
            tag.id: min(
                1.0,
                profile.tag_weights.get(tag.id, 0)
                * tag.confidence
                * candidate.tag_quality_weights.get(tag.id, 1)
                / 2,
            )
            for tag in features.tags
            if profile.tag_weights.get(tag.id, 0) > 0
        }
        signals = {tag: value for tag, value in signals.items() if value > 0}
        indirect = {
            tag.id: min(0.25, profile.counterparty_tag_weights.get(tag.id, 0))
            * tag.confidence
            * min(1, candidate.tag_quality_weights.get(tag.id, 1))
            for tag in features.tags
            if profile.counterparty_tag_weights.get(tag.id, 0) > 0
        }
        direct = bool(direct_topics & signals.keys())
        specific = features.business_scope in {"local", "organization"}
        if (not signals and not indirect) or features.business_relevance < 0.3:
            continue
        if specific and not direct:
            continue
        match = max(
            [
                *indirect.values(),
                *(
                    value * (1 if tag in direct_topics else 0.7)
                    for tag, value in signals.items()
                ),
            ]
        )
        age_days = max(
            0, (request.now - candidate.published_at).total_seconds() / 86400
        )
        freshness = 1 / (1 + age_days / 3)
        geography, geography_reason = geography_match(profile, features.geography)
        factor = 1.0
        if specific and geography == 0:
            factor = 0.3 if profile.operating_region_codes else 0.6
            if (
                profile.country_code
                and features.geography.country_code
                and profile.country_code != features.geography.country_code
            ):
                factor = 0.2
        base = match * features.business_relevance * (0.85 + 0.15 * freshness) * factor
        bonus = 0.1 * (geography or 0) * base * (1 - base)
        items.append(
            RankedNews(
                news_id=features.news_id,
                match_score=match,
                freshness_score=freshness,
                final_score=base + bonus,
                geography_score=geography,
                geography_bonus=bonus,
                geography_factor=factor,
                geography_reason=geography_reason,
                ranking_version=RANKING_VERSION,
                matched_signals=sorted(signals),
                counterparty_signals=sorted(
                    tag
                    for tag in indirect
                    if indirect[tag]
                    > signals.get(tag, 0) * (1 if tag in direct_topics else 0.7)
                ),
                reason=("Совпали темы профиля: " + ", ".join(sorted(signals)))
                if signals
                else "Новость об отрасли контрагентов из платёжной выборки",
            )
        )
    items.sort(key=lambda item: (-item.final_score, str(item.news_id)))
    return RankingResult(
        method="weighted_formula_v1", version=RANKING_VERSION, items=items
    )
