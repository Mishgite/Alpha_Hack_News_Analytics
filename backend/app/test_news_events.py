"""проверяет группировку событий, сохранность публикаций и ограничение контекста без платных вызовов"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.demo_data import COMPANY_ID, TAG_ID, create_demo_data
from app.infrastructure.news_matching import same_event
from app.schemas.news import (
    Geography,
    NewsFeatures,
    NewsPublication,
    NewsTag,
    StoredNews,
)
from app.schemas.services import AnalysisVersions, IncomingNews, Registration
from app.services.ai_agents.analysis import event_sources
from app.test_backend import database, services  # noqa: F401

TITLE = "ЦБ сохранил ключевую ставку на уровне 14 процентов"
OTHER_TITLE = "Банк России оставил ключевую ставку на уровне 14 процентов"
BODY = "Совет директоров Банка России сохранил ключевую ставку на уровне 14 процентов. Решение принято на заседании регулятора. Дальнейшие решения будут зависеть от динамики инфляции и ожиданий населения."
OTHER_BODY = "На заседании совет директоров Банка России оставил ключевую ставку на уровне 14 процентов. Регулятор будет принимать дальнейшие решения с учётом динамики инфляции и ожиданий населения."


def test_reworded_event_matches():
    assert same_event(TITLE, BODY, OTHER_TITLE, OTHER_BODY)
    assert same_event(OTHER_TITLE, OTHER_BODY, TITLE, BODY)


@pytest.mark.parametrize(
    "title,body",
    [
        (OTHER_TITLE.replace("14", "15"), OTHER_BODY.replace("14", "15")),
        (OTHER_TITLE.replace("оставил", "повысил"), OTHER_BODY),
        (OTHER_TITLE.replace("оставил", "не оставил"), OTHER_BODY),
        (OTHER_TITLE.replace("Банк России", "Сбербанк"), OTHER_BODY),
        ("ЦБ обсуждает банковский сектор", "Изменения банковского сектора"),
    ],
)
def test_different_facts_do_not_match(title, body):
    assert not same_event(TITLE, BODY, title, body)


def test_different_cities_do_not_match():
    title = "Сбербанк открыл новый крупный офис в Москве"
    body = "Новый крупный офис начал работу для обслуживания предприятий и населения, сообщил представитель банка. Клиенты смогут получить консультации по банковским продуктам и услугам."
    assert not same_event(title, body, title.replace("Москве", "Самаре"), body)
    assert not same_event(
        title, body + " В Москве открыли офис", title, body + " В Самаре открыли офис"
    )


def test_amount_units_do_not_disappear():
    title = "Сбербанк увеличил объём финансирования нового проекта"
    body = "Банк выделил 5 млн рублей на расширение предприятия и обновление оборудования, новая производственная линия позволит увеличить выпуск продукции в следующем году"
    assert not same_event(title, body, title, body.replace("млн", "млрд"))


def test_group_preserves_texts_reuses_exact_tags_and_can_be_split(services):  # noqa: F811
    news = services["news"]
    stamp = datetime.now(UTC) - timedelta(minutes=10)
    sources = ["event-" + uuid4().hex for _ in range(4)]
    for source in sources:
        news.register_source(source, kind="rss")
    first = IncomingNews(
        source=sources[0],
        external_id="one",
        url="https://example.org/one",
        title=TITLE,
        body=BODY,
        published_at=stamp,
    )
    second = first.model_copy(
        update={
            "source": sources[1],
            "external_id": "two",
            "url": "https://example.org/two",
            "title": OTHER_TITLE,
            "body": OTHER_BODY,
        }
    )
    a = news.save_news(first)
    b = news.save_news(second)
    a = news.get_news(a.news_id)
    assert (
        a.news_id != b.news_id and a.event_id == b.event_id and a.event_id is not None
    )
    assert {p.text for p in a.publications} == {BODY, OTHER_BODY}
    assert {p.source_url for p in a.publications} == {first.url, second.url}
    with services["uow"]() as db:
        ranked = [
            SimpleNamespace(news_id=b.news_id),
            SimpleNamespace(news_id=a.news_id),
        ]
        assert db.news.unique_events(ranked) == ranked[:1]
    create_demo_data(profiles=services["profiles"], news=news)
    news.save_features(
        NewsFeatures(
            news_id=a.news_id,
            tags=[NewsTag(id=TAG_ID, confidence=1)],
            geography=Geography(),
            summary="Ставка сохранена",
        ),
        version="test",
        expected_content_hash=a.content_hash,
    )
    news.save_features(
        NewsFeatures(
            news_id=b.news_id,
            tags=[NewsTag(id=TAG_ID, confidence=1)],
            geography=Geography(),
            summary="Ставка сохранена",
        ),
        version="test",
        expected_content_hash=b.content_hash,
    )
    user = (
        services["profiles"]
        .register_demo(Registration(company_id=COMPANY_ID, job_role="ceo"))
        .user
    )
    page = services["feed"].create_feed(user.id)
    assert (
        len({item.ranking.news_id for item in page.items} & {a.news_id, b.news_id}) == 1
    )
    job = services["insights"].request_analysis(
        user.id, a.news_id, idempotency_key="event-test"
    )
    claimed = services["insights"].claim_job("event-test")
    assert claimed.id == job.id
    versions = AnalysisVersions(
        model_id="test",
        prompt_version="test",
        report_corpus_version="test",
        agent_version="test",
        retrieval_version="test",
    )
    work = services["insights"].prepare_job(
        job.id, "event-test", claimed.attempts, versions=versions
    )
    exact = news.save_news(
        first.model_copy(
            update={
                "source": sources[2],
                "external_id": "three",
                "url": "https://example.org/three",
            }
        )
    )
    assert exact.news_id != a.news_id
    assert exact.tagging_status == "ready" and exact.features.news_id == exact.news_id
    with pytest.raises(ValueError, match="News changed"):
        services["insights"].get_cached_result(work)
    assert news.save_news(second).news_id == b.news_id
    news.save_news(
        first.model_copy(
            update={
                "body": BODY.replace("14", "15"),
                "title": TITLE.replace("14", "15"),
            }
        )
    )
    assert news.get_news(exact.news_id).text == BODY
    assert news.get_news(a.news_id).event_id != news.get_news(b.news_id).event_id
    old = news.save_news(
        second.model_copy(
            update={
                "source": sources[3],
                "external_id": "four",
                "published_at": stamp - timedelta(days=7),
            }
        )
    )
    assert old.event_id is None
    detached = news.separate_event(b.news_id)
    assert len(detached.publications) == 1
    news.group_existing_news(days=10)
    assert news.get_news(b.news_id).event_id == detached.event_id
    assert len(news.get_news(b.news_id).publications) == 1


def test_event_context_stays_within_original_budget():
    article = StoredNews(
        news_id=uuid4(),
        title=TITLE,
        text="слово " * 10000,
        published_at=datetime.now(UTC),
        content_hash="main",
        tagging_status="ready",
    )
    for number in range(6):
        article.publications.append(
            NewsPublication(
                news_id=uuid4(),
                publication_id=uuid4(),
                title=OTHER_TITLE,
                text="другой текст " * 10000,
                published_at=article.published_at,
                content_hash=str(number),
            )
        )
    sources = event_sources(article)
    assert len(sources) == 3
    assert sum(len(value["text"]) for value in sources.values()) == 18000
    assert all(value["reference"].kind == "news" for value in sources.values())


def test_pending_exact_copies_are_tagged_once_even_without_event(services):  # noqa: F811
    news = services["news"]
    copies = []
    for number in range(2):
        source = "short-copy-" + uuid4().hex
        news.register_source(source, kind="rss")
        copies.append(
            news.save_news(
                IncomingNews(
                    source=source,
                    external_id="one",
                    title="Короткое сообщение",
                    body="Недостаточно текста для объединения в событие",
                    published_at=datetime.now(UTC),
                )
            )
        )
    assert all(copy.event_id is None for copy in copies)
    ids = {copy.news_id for copy in copies}
    assert len(ids & {item.news_id for item in news.list_pending_news(limit=500)}) == 1
    news.save_features(
        NewsFeatures(news_id=copies[0].news_id, tags=[], geography=Geography()),
        version="test",
        expected_content_hash=copies[0].content_hash,
    )
    assert all(news.get_news(news_id).tagging_status == "ready" for news_id in ids)
