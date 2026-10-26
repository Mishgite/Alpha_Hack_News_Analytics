"""проверяет рекомендации, поиск и цитаты без вызова модели, сохраняет воспроизводимый отчёт"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from math import log2
from pathlib import Path
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.database.uow import UnitOfWork
from app.infrastructure.news_matching import VERSION, same_event
from app.schemas.news import Geography, NewsFeatures, NewsTag
from app.schemas.ranking import NewsCandidate, RankingProfile, RankingRequest
from app.services.ai_agents.analysis import normalized
from app.services.ranking import RANKING_VERSION, rank_news

ROOT = Path(__file__).resolve().parent


def source_version():
    """считает версию кода и справочников, не обходя окружение Python"""
    source = {}
    for directory, folders, files in os.walk(ROOT):
        folders[:] = sorted(
            name for name in folders if name not in {".venv", "__pycache__"}
        )
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix not in {".py", ".json"} or name in {
                "main.py",
                "bad_news.json",
            }:
                continue
            source[path.relative_to(ROOT).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return fingerprint(source)


def failed_checks(regression, actual=None):
    """применяет одинаковые пороги в консоли и воркере, не подменяет отсутствующие оценки нулём"""
    minimums = {
        "precision_at_5": 0.8,
        "ndcg_at_10": 0.9,
        "duplicate_precision": 1,
        "duplicate_recall": 1,
    }
    failures = [
        name
        for name, minimum in minimums.items()
        if regression.get(name) is None or regression[name] < minimum
    ]
    if actual is not None:
        for name, minimum in {
            "retrieval_recall_at_5": 0.8,
            "retrieval_negative_accuracy": 1,
        }.items():
            if actual.get(name) is None or actual[name] < minimum:
                failures.append(name)
        for name, minimum in {
            "exact_quote_rate": 1,
            "reference_coverage": 1,
            "semantic_support_rate": 0.9,
        }.items():
            if actual.get(name) is not None and actual[name] < minimum:
                failures.append(name)
        if not actual.get("bank_reference_valid", False):
            failures.append("bank_reference_valid")
    return failures


def fingerprint(value):
    """фиксирует состав данных независимо от порядка ключей JSON"""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def ndcg(actual, ideal, k=10):
    """сравнивает порядок выдачи с оценками релевантности 0..3"""

    def dcg(values):
        return sum(
            (2**grade - 1) / log2(index + 2) for index, grade in enumerate(values[:k])
        )

    maximum = dcg(sorted(ideal, reverse=True))
    return dcg(actual) / maximum if maximum else None


def offline(cases):
    """проверяет фиксированные синтетические случаи, не выдавая их за экспертную оценку живой ленты"""
    now = datetime(2026, 10, 26, tzinfo=UTC)
    scores = []
    for case in cases["ranking"]:
        profile = RankingProfile(
            user_id=UUID(int=1),
            company_id=case["id"],
            job_role="ceo",
            profile_version="evaluation-v1",
            tag_weights={case["topic"]: 1.5, case["role"]: 1},
            company_tag_ids=[case["topic"]],
        )
        candidates = [
            NewsCandidate(
                published_at=now - timedelta(days=n["age_days"]),
                features=NewsFeatures(
                    news_id=UUID(int=i + 1),
                    tags=[NewsTag(id=n["tag"], confidence=1)],
                    geography=Geography(),
                    business_scope=n["scope"],
                    business_relevance=1,
                ),
            )
            for i, n in enumerate(case["news"])
        ]
        ranked = rank_news(
            RankingRequest(profile=profile, candidates=candidates, now=now)
        ).items
        labels = {UUID(int=i + 1): n["relevance"] for i, n in enumerate(case["news"])}
        actual = [labels[item.news_id] for item in ranked]
        scores.append(
            {
                "case": case["id"],
                "precision_at_5": sum(v > 0 for v in actual[:5]) / 5,
                "ndcg_at_10": ndcg(actual, list(labels.values())),
            }
        )
    pairs = [
        {"expected": c["same"], "actual": same_event(*c["left"], *c["right"])}
        for c in cases["duplicates"]
    ]
    tp = sum(p["actual"] and p["expected"] for p in pairs)
    predicted = sum(p["actual"] for p in pairs)
    positives = sum(p["expected"] for p in pairs)
    return {
        "label_source": cases["label_source"],
        "cases": scores,
        "precision_at_5": sum(s["precision_at_5"] for s in scores) / len(scores),
        "ndcg_at_10": sum(s["ndcg_at_10"] for s in scores) / len(scores),
        "duplicate_precision": tp / predicted if predicted else None,
        "duplicate_recall": tp / positives if positives else None,
        "duplicate_cases": pairs,
    }


def statements(result):
    """собирает утверждения всех разделов и отдельный вывод по аналитике банка"""
    values = [
        item
        for section in (
            "facts",
            "why_important",
            "risks",
            "opportunities",
            "recommendations",
        )
        for item in result.get(section, [])
    ]
    if result.get("bank_position"):
        values.append(result["bank_position"])
    return values


def audit_quotes(result):
    """проверяет наличие ссылок и точность цитат в сохранённых выдержках, не оценивает смысл вывода"""
    sources = {s["id"]: s for s in result.get("source_refs", [])}
    entries = statements(result)
    valid, total, covered = 0, 0, 0
    for item in entries:
        refs = item.get("source_refs", [])
        covered += bool(refs and all(ref in sources for ref in refs))
        for ref in refs:
            total += 1
            quote = normalized(item.get("evidence_quotes", {}).get(ref, ""))
            valid += len(quote) >= 12 and quote in normalized(
                sources.get(ref, {}).get("excerpt") or ""
            )
    bank = result.get("bank_position")
    bank_valid = bank is None or any(
        sources.get(ref, {}).get("kind") == "bank_report"
        for ref in bank.get("source_refs", [])
    )
    return {
        "statements": len(entries),
        "covered": covered,
        "quotes": total,
        "valid_quotes": valid,
        "bank_reference_valid": bank_valid,
    }


def database_checks(cases, *, uow_factory=UnitOfWork):
    """проверяет настоящий поисковый индекс и сохранённые разборы в одной версии корпуса"""
    retrieval = []
    with uow_factory() as db:
        corpus = fingerprint(db.reports.versions())
        for case in cases["retrieval"]:
            found = db.reports.search(case["query"], limit=5)
            names = {c.filename for c in found}
            expected = set(case["expected"])
            retrieval.append(
                {
                    **case,
                    "found": [
                        {"file": c.filename, "page": c.page_num, "id": str(c.id)}
                        for c in found
                    ],
                    "passed": bool(expected & names) if expected else not found,
                }
            )
        analyses = db.quality.recent_analyses(100)
        results = []
        review = []
        for analysis in analyses:
            audit = audit_quotes(analysis["result"])
            results.append(
                {key: analysis[key] for key in ("id", "model", "prompt", "corpus")}
                | audit
            )
            review.append(
                {
                    **analysis,
                    "fingerprint": fingerprint(analysis),
                    "supported": None,
                    "reviewer": "",
                    "reason": "",
                }
            )
        positives = [r for r in retrieval if r["expected"]]
        negatives = [r for r in retrieval if not r["expected"]]
        quotes = sum(a["quotes"] for a in results)
        count = sum(a["statements"] for a in results)
        metrics = {
            "analysis_count": len(analyses),
            "analyses_with_bank_sources": sum(
                any(
                    s.get("kind") == "bank_report"
                    for s in a["result"].get("source_refs", [])
                )
                for a in analyses
            ),
            "retrieval_recall_at_5": sum(r["passed"] for r in positives)
            / len(positives),
            "retrieval_negative_accuracy": sum(r["passed"] for r in negatives)
            / len(negatives),
            "exact_quote_rate": sum(a["valid_quotes"] for a in results) / quotes
            if quotes
            else None,
            "reference_coverage": sum(a["covered"] for a in results) / count
            if count
            else None,
            "bank_reference_valid": all(a["bank_reference_valid"] for a in results),
            "analyses": results,
            "retrieval": retrieval,
            "usefulness": db.quality.snapshot()["usefulness_30d"],
            "semantic_support_rate": None,
            "human_reviews": 0,
        }
        if fingerprint(db.reports.versions()) != corpus:
            raise ValueError("Report corpus changed during evaluation")
        return corpus, metrics, review


def apply_reviews(metrics, template, reviews):
    """принимает оценки только для неизменённых результатов, без пустых имён проверяющего"""
    expected = {item["id"]: item["fingerprint"] for item in template}
    accepted = []
    seen = set()
    for review in reviews:
        if review["id"] in seen or expected.get(review["id"]) != review.get(
            "fingerprint"
        ):
            raise ValueError("Repeated or outdated human review")
        seen.add(review["id"])
        if review.get("supported") is None:
            continue
        if (
            type(review["supported"]) is not bool
            or not review.get("reviewer", "").strip()
            or not review.get("reason", "").strip()
        ):
            raise ValueError(
                "A review requires supported=true/false, reviewer and reason"
            )
        accepted.append(review)
    metrics["human_reviews"] = len(accepted)
    metrics["semantic_support_rate"] = (
        sum(r["supported"] for r in accepted) / len(accepted) if accepted else None
    )


def regressions(report, baseline):
    """отказывается сравнивать разные контрольные наборы или корпуса"""
    if any(
        report.get(key) != baseline.get(key)
        for key in ("cases_hash", "corpus", "database_enabled")
    ):
        raise ValueError("Baseline uses another dataset, corpus or evaluation mode")
    failures = []
    for section, names in (
        (
            "offline",
            ("precision_at_5", "ndcg_at_10", "duplicate_precision", "duplicate_recall"),
        ),
        ("database", ("retrieval_recall_at_5", "retrieval_negative_accuracy")),
    ):
        for name in names:
            previous = baseline.get(section, {}).get(name)
            current = report.get(section, {}).get(name)
            if previous is not None and (current is None or current < previous - 1e-9):
                failures.append(section + "." + name)
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "data/evaluation")
    args = parser.parse_args()
    if args.reviews and not args.database:
        parser.error("--reviews requires --database")
    cases = json.loads((ROOT / "evaluation_cases.json").read_text(encoding="utf-8"))
    revision = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if shutil.which("git")
        else None
    )
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "git_revision": revision,
        "source_hash": source_version(),
        "cases_hash": fingerprint(cases),
        "ranking_version": RANKING_VERSION,
        "dedup_version": VERSION,
        "database_enabled": args.database,
        "corpus": None,
        "offline": offline(cases),
    }
    review = []
    if args.database:
        report["corpus"], report["database"], review = database_checks(cases)
        if args.reviews:
            apply_reviews(
                report["database"],
                review,
                json.loads(args.reviews.read_text(encoding="utf-8")),
            )
    report["regressions"] = (
        regressions(report, json.loads(args.baseline.read_text(encoding="utf-8")))
        if args.baseline
        else []
    )
    report["failed_checks"] = failed_checks(report["offline"], report.get("database"))
    report["checks_passed"] = not (report["failed_checks"] or report["regressions"])
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = args.output / (stamp + ".json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if review:
        (args.output / (stamp + "-review.json")).write_text(
            json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    lines = [
        "# Проверка качества",
        "",
        f"Время: {report['created_at']}",
        f"Код: `{report['source_hash']}`",
        "",
        "## Синтетические контрольные случаи",
        "",
    ]
    lines += [
        f"- {k}: {v}"
        for k, v in report["offline"].items()
        if isinstance(v, (int, float))
    ]
    if args.database:
        lines += ["", "## Реальная БД", ""] + [
            f"- {k}: {v if v is not None else 'нет оценки'}"
            for k, v in report["database"].items()
            if not isinstance(v, (dict, list))
        ]
    lines += [
        "",
        "Точность цитат проверена по сохранённым выдержкам; смысловая подтверждённость оценивается отдельно",
        f"Проверки: {'пройдены' if report['checks_passed'] else 'есть ошибки'}",
        f"Регрессии: {report['regressions']}",
        f"Нарушенные пороги: {report['failed_checks']}",
    ]
    path.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(path)
    print("PASS" if report["checks_passed"] else "FAIL")
    return 0 if report["checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
