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
    result = rank_news(
        RankingRequest(profile=director, candidates=candidates, now=now)
    )
    assert result.items[0].news_id == candidates[0].features.news_id
    result = rank_news(
        RankingRequest(profile=accountant, candidates=candidates, now=now)
    )
    assert result.items[0].news_id == candidates[1].features.news_id
    inputs.disabled_tag_ids = ["biz_tax"]
    assert build_profile(inputs, default_policy()).tag_weights["biz_tax"] == 0
