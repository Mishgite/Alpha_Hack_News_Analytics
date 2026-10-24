"""временная формула для проверки API до подключения обученной модели"""

from app.schemas.ranking import RankedNews, RankingRequest, RankingResult


def rank_news(request: RankingRequest) -> RankingResult:
    """сортирует по совпадению тем и свежести, при равных баллах использует ID новости

    паттерн Strategy: функцию получает FeedService, замена модели не меняет API
    совпадение считается по самой подходящей теме
    свежесть равна 1 / (1 + возраст в днях)
    итог содержит 80% совпадения и 20% свежести, это заглушка без обучения
    """
    items = []
    for candidate in request.candidates:
        signals = {
            tag.id: request.profile.tag_weights.get(tag.id, 0)
            * tag.confidence
            * candidate.tag_quality_weights.get(tag.id, 1)
            / 2
            for tag in candidate.features.tags
            if request.profile.tag_weights.get(tag.id, 0) > 0
        }
        match = min(1.0, max(signals.values(), default=0.0))
        age_days = max(
            0, (request.now - candidate.published_at).total_seconds() / 86400
        )
        freshness = 1 / (1 + age_days)
        matched = sorted(tag for tag, value in signals.items() if value > 0)
        items.append(
            RankedNews(
                news_id=candidate.features.news_id,
                match_score=match,
                freshness_score=freshness,
                final_score=0.8 * match + 0.2 * freshness,
                matched_signals=matched,
                reason=(
                    "Тестовое ранжирование: совпали темы " + ", ".join(matched)
                    if matched
                    else "Тестовое ранжирование: совпадений тем нет, учтена свежесть"
                ),
            )
        )
    items.sort(key=lambda item: (-item.final_score, str(item.news_id)))
    return RankingResult(method="weighted_formula_v1", version="stub-v1", items=items)
