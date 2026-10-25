"""проверяет географический бонус, нормализацию адресов и работу без географии"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.schemas.database import CompanyData
from app.schemas.news import Geography, NewsFeatures, NewsTag
from app.schemas.ranking import NewsCandidate, RankingProfile, RankingRequest
from app.services.geography import city_region, company_geography, resolve_region
from app.services.ranking import geography_match, rank_news


def profile(**values):
    """создаёт профиль с одним тематическим интересом для сравнения географии"""
    return RankingProfile(
        user_id=uuid4(),
        company_id="test",
        job_role="ceo",
        tag_weights={"biz_agr": 1},
        profile_version="test",
        **values,
    )


@pytest.mark.parametrize(
    "city,expected",
    [
        ("г. Сочи", "reg_23"),
        ("город Казань", "reg_16"),
        ("Moscow", "reg_77"),
        ("г. Санкт-Петербург", "reg_78"),
        ("Сергиев Посад", "reg_50"),
        ("Алдан", "reg_14"),
        ("неизвестный город", None),
        ("Киров", None),
    ],
)
def test_city_region(city, expected):
    """распознаёт города по справочнику и оставляет неоднозначные названия пустыми"""
    assert city_region(city) == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Краснодарский край", "reg_23"),
        ("Московская обл.", "reg_50"),
        ("Башкортостан (Республика)", "reg_02"),
        ("reg_77", "reg_77"),
        ("Чувашская Республика-Чувашия", "reg_21"),
        ("Кемеровская область", "reg_42"),
    ],
)
def test_region_aliases(name, expected):
    """проверяет варианты регионов из импортированных профилей"""
    assert resolve_region(name) == expected


def test_company_address_is_not_operating_geography():
    """город регистрации не становится регионом деятельности, противоречия не угадываются"""
    company = CompanyData(id="one", profile_version="one", city="г. Сочи")
    assert company_geography(company) == ("RU", "reg_23", None)
    company.region = "Московская область"
    assert company_geography(company)[1] is None
    company.registered_region_code = "unknown"
    assert company_geography(company)[1] is None
    company.registered_region_code = "reg_23"
    company.operating_region_codes = ["Республика Татарстан"]
    assert company_geography(company)[1:] == ("reg_23", ["reg_16"])
    assert city_region("Киров", "reg_43") == "reg_43"


def test_geography_scope_and_priority():
    """проверяет приоритет деятельности, федеральный масштаб и неизвестную географию"""
    p = profile(
        country_code="RU",
        registered_region_code="reg_23",
        operating_region_codes=["reg_16"],
    )
    assert (
        geography_match(p, Geography(country_code="RU", region_codes=["reg_23"]))[0]
        == 0
    )
    assert (
        geography_match(
            p, Geography(country_code="RU", region_codes=["reg_16", "reg_23"])
        )[0]
        == 1
    )
    assert geography_match(p, Geography(country_code="RU", nationwide=True))[0] == 1
    assert geography_match(p, Geography(country_code="US", nationwide=True))[0] == 0
    assert geography_match(p, Geography(country_code="RU", nationwide=False))[0] is None
    assert geography_match(p, Geography(nationwide=True))[0] is None
    assert geography_match(profile(), Geography(region_codes=["reg_23"]))[0] is None
    assert (
        geography_match(
            profile(registered_region_code="reg_77"), Geography(region_codes=["reg_50"])
        )[0]
        == 0
    )
    assert (
        geography_match(
            profile(registered_region_code="reg_78"), Geography(region_codes=["reg_47"])
        )[0]
        == 0
    )


def test_city_codes_match_their_region():
    """код города события сопоставляется с областью без сравнения подстрок"""
    from app.services.tag_catalog import load_catalog

    city = next(
        code for name, code in load_catalog()["city"].items() if " / Сочи (" in name
    )
    assert (
        geography_match(
            profile(operating_region_codes=["reg_23"]), Geography(city_codes=[city])
        )[0]
        == 1
    )


def test_formula_optional_bonus_and_bounds():
    """география усиливает подходящую тему, но не поднимает постороннюю новость сама по себе"""
    now = datetime.now(UTC)

    def candidate(geography, tag="biz_agr"):
        return NewsCandidate(
            published_at=now - timedelta(days=1),
            features=NewsFeatures(
                news_id=uuid4(),
                tags=[NewsTag(id=tag, confidence=1)],
                geography=geography,
            ),
        )

    candidates = [
        candidate(Geography(region_codes=["reg_23"])),
        candidate(Geography(region_codes=["reg_16"])),
        candidate(Geography()),
        candidate(Geography(region_codes=["reg_23"]), "biz_air"),
    ]
    p = profile(operating_region_codes=["reg_23"])
    result = rank_news(RankingRequest(profile=p, candidates=candidates, now=now))
    scores = {item.news_id: item for item in result.items}
    local, other, unknown = [scores[c.features.news_id] for c in candidates[:3]]
    assert candidates[3].features.news_id not in scores
    assert local.final_score > other.final_score == unknown.final_score
    registered = rank_news(
        RankingRequest(
            profile=profile(registered_region_code="reg_23"),
            candidates=candidates[:1],
            now=now,
        )
    ).items[0]
    assert other.final_score < registered.final_score < local.final_score
    assert result.items[0].news_id == local.news_id
    assert all(0 <= item.final_score <= 1 for item in result.items)
    p.tag_weights["biz_agr"] = 2
    candidates[0].published_at = now
    assert (
        rank_news(RankingRequest(profile=p, candidates=candidates[:1], now=now))
        .items[0]
        .final_score
        <= 1
    )


def test_local_investment_requires_company_topic_or_personal_choice():
    """общий интерес директора не делает чужую стройку полезной IT-компании"""
    now = datetime.now(UTC)
    p = profile(
        company_tag_ids=["biz_it"], country_code="RU", registered_region_code="reg_77"
    )
    p.tag_weights = {"biz_it": 1.5, "biz_investment": 1.2}
    news = NewsCandidate(
        published_at=now,
        features=NewsFeatures(
            news_id=uuid4(),
            tags=[NewsTag(id="biz_investment", confidence=1)],
            geography=Geography(country_code="US"),
            business_scope="organization",
            business_relevance=0.4,
        ),
    )
    request = RankingRequest(profile=p, candidates=[news], now=now)
    assert rank_news(request).items == []
    p.personal_tag_ids = ["biz_investment"]
    item = rank_news(request).items[0]
    assert item.geography_factor == 0.2
    p.tag_weights["biz_investment"] = 0
    assert rank_news(request).items == []


def test_weak_events_and_zero_quality_do_not_fill_feed():
    """школьное мероприятие и забракованные теги не дополняют ленту ради количества"""
    now = datetime.now(UTC)
    p = profile(company_tag_ids=["biz_agr"])
    weak = NewsCandidate(
        published_at=now,
        features=NewsFeatures(
            news_id=uuid4(),
            tags=[NewsTag(id="biz_agr", confidence=1)],
            geography=Geography(),
            business_relevance=0.1,
        ),
    )
    invalid = weak.model_copy(deep=True)
    invalid.features.news_id = uuid4()
    invalid.features.business_relevance = 0.8
    invalid.tag_quality_weights = {"biz_agr": 0}
    assert not rank_news(
        RankingRequest(profile=p, candidates=[weak, invalid], now=now)
    ).items


def test_local_geography_is_weaker_when_only_registration_is_known():
    """несовпадение регистрации снижает балл слабее несовпадения известных регионов работы"""
    now = datetime.now(UTC)
    candidate = NewsCandidate(
        published_at=now,
        features=NewsFeatures(
            news_id=uuid4(),
            tags=[NewsTag(id="biz_agr", confidence=1)],
            geography=Geography(region_codes=["reg_16"]),
            business_scope="local",
            business_relevance=0.8,
        ),
    )
    p = profile(company_tag_ids=["biz_agr"], registered_region_code="reg_77")
    request = RankingRequest(profile=p, candidates=[candidate], now=now)
    registered = rank_news(request).items[0]
    p.operating_region_codes = ["reg_77"]
    operating = rank_news(request).items[0]
    assert 0 < operating.final_score < registered.final_score
    candidate.features.business_scope = "industry"
    assert rank_news(request).items[0].geography_factor == 1


def test_company_identifier_does_not_artificially_shuffle_results():
    """разные ID при одинаковых признаках не создают видимость персонализации"""
    now = datetime.now(UTC)
    p = profile()
    candidates = [
        NewsCandidate(
            published_at=now,
            features=NewsFeatures(
                news_id=uuid4(),
                tags=[NewsTag(id="biz_agr", confidence=0.5 + i / 10)],
                geography=Geography(),
            ),
        )
        for i in range(3)
    ]
    request = RankingRequest(profile=p, candidates=candidates, now=now)
    first = rank_news(request)
    p.company_id = "another"
    p.user_id = uuid4()
    assert rank_news(request) == first
