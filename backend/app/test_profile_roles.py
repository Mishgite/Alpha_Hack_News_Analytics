"""проверяет влияние должности на порядок новостей"""

from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.database import CompanyData, CompanyTagInput, ProfileInputs, UserData
from app.schemas.news import Geography, NewsFeatures, NewsTag
from app.schemas.ranking import NewsCandidate, RankingRequest
from app.services.profile_policy import default_policy
from app.services.profiles import build_profile
from app.services.ranking import rank_news


def test_role_changes_ranking_and_respects_disabled_topics():
    """одна компания получает разный порядок новостей для директора и бухгалтера"""
    now = datetime.now(UTC)
    inputs = ProfileInputs(
        user=UserData(
            id=uuid4(), company_id="test", city="", job_role="ceo", access_role="user"
        ),
        company=CompanyData(id="test", profile_version="1"),
        company_tags=[
            CompanyTagInput(tag_id=tag, origin="rule", base_weight=1)
            for tag in ("biz_investment", "biz_tax")
        ],
        personal_tag_ids=[],
        disabled_tag_ids=[],
        reaction_counts={},
    )
    candidates = [
        NewsCandidate(
            published_at=now,
            features=NewsFeatures(
                news_id=uuid4(),
                tags=[NewsTag(id=tag, confidence=1)],
                geography=Geography(),
            ),
        )
        for tag in ("biz_investment", "biz_tax")
    ]
    director = build_profile(inputs, default_policy())
    inputs.user.job_role = "accountant"
    accountant = build_profile(inputs, default_policy())
    assert director.profile_version != accountant.profile_version
    result = rank_news(RankingRequest(profile=director, candidates=candidates, now=now))
    assert result.items[0].news_id == candidates[0].features.news_id
    result = rank_news(
        RankingRequest(profile=accountant, candidates=candidates, now=now)
    )
    assert result.items[0].news_id == candidates[1].features.news_id
    inputs.disabled_tag_ids = ["biz_tax"]
    assert build_profile(inputs, default_policy()).tag_weights["biz_tax"] == 0


def test_company_topics_change_order_for_the_same_role():
    """отрасль меняет первое место при одинаковых должности и датах новостей"""
    from app.services.company_topics import initial_company_topics

    now = datetime.now(UTC)
    candidates = [
        NewsCandidate(
            published_at=now,
            features=NewsFeatures(
                news_id=uuid4(),
                tags=[NewsTag(id=tag, confidence=1)],
                geography=Geography(),
            ),
        )
        for tag in ("biz_it", "biz_freight", "biz_investment")
    ]
    first = []
    for code in ("62.01", "49.4"):
        company = CompanyData(id=code, profile_version="1", okved_code=code)
        inputs = ProfileInputs(
            user=UserData(
                id=uuid4(), company_id=code, city="", job_role="ceo", access_role="user"
            ),
            company=company,
            company_tags=initial_company_topics(company),
            personal_tag_ids=[],
            disabled_tag_ids=[],
            reaction_counts={},
        )
        result = rank_news(
            RankingRequest(
                profile=build_profile(inputs, default_policy()),
                candidates=candidates,
                now=now,
            )
        )
        first.append(result.items[0].news_id)
    assert first == [candidates[0].features.news_id, candidates[1].features.news_id]


def test_company_topic_rules_use_known_tags_and_do_not_guess_missing_codes():
    """неизвестный ОКВЭД не создаёт выдуманные темы, все правила есть в справочнике"""
    from app.services.company_topics import OKVED_TOPICS, initial_company_topics
    from app.services.tag_catalog import load_catalog

    known = set(load_catalog()["business"].values())
    assert all(set(tags) <= known for tags in OKVED_TOPICS.values())
    for code in (None, "unknown", "99.99", "6201"):
        assert (
            initial_company_topics(
                CompanyData(id="test", profile_version="1", okved_code=code)
            )
            == []
        )
    tags = initial_company_topics(
        CompanyData(id="test", profile_version="1", okved_code="47.91.2")
    )
    assert {t.tag_id for t in tags} == {"biz_retail", "biz_ecom"}


def test_manual_company_topic_is_not_rejected_by_local_event_filter():
    """ручная тема дополняет ОКВЭД и допускает локальную новость до её отключения"""
    now = datetime.now(UTC)
    inputs = ProfileInputs(
        user=UserData(
            id=uuid4(),
            company_id="test",
            city="",
            job_role="employee",
            access_role="user",
        ),
        company=CompanyData(id="test", profile_version="1", okved_code="62.01"),
        company_tags=[
            CompanyTagInput(tag_id="biz_health", origin="manual", base_weight=1.5)
        ],
        personal_tag_ids=[],
        disabled_tag_ids=[],
        reaction_counts={},
    )
    candidate = NewsCandidate(
        published_at=now,
        features=NewsFeatures(
            news_id=uuid4(),
            tags=[NewsTag(id="biz_health", confidence=1)],
            geography=Geography(),
            business_scope="local",
            business_relevance=0.8,
        ),
    )
    result = rank_news(
        RankingRequest(
            profile=build_profile(inputs, default_policy()),
            candidates=[candidate],
            now=now,
        )
    )
    assert [item.news_id for item in result.items] == [candidate.features.news_id]
    inputs.disabled_tag_ids = ["biz_health"]
    assert not rank_news(
        RankingRequest(
            profile=build_profile(inputs, default_policy()),
            candidates=[candidate],
            now=now,
        )
    ).items
