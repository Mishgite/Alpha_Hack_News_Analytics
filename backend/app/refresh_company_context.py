"""обновляет вычисляемый контекст выбранных компаний, не повторяя разметку неизменившейся деятельности"""

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infrastructure.database.uow import UnitOfWork
from app.infrastructure.database.worker_lock import company_tagging_lock
from app.services.company_context import enrich_companies
from app.services.profile_pipeline import ProfilePipeline


def refresh(directory, *, uow_factory=UnitOfWork):
    """сверяет версии перед сохранением и сохраняет разметку только при неизменном входе разметчика"""
    with uow_factory() as db:
        selection = db.runtime.get("demo_companies")
        if not selection or not selection["value"].get("ids"):
            raise ValueError("Company selection is empty")
        original = [db.companies.get(id) for id in selection["value"]["ids"]]
        if any(company is None for company in original):
            raise ValueError("Selected company is missing")
    enriched = enrich_companies(original, directory)
    updated = 0
    for old, new in zip(original, enriched, strict=True):
        with company_tagging_lock(old.id), uow_factory() as db:
            if db.companies.get(old.id) != old:
                raise ValueError("Company changed during context refresh")
            if old == new:
                continue
            state = db.runtime.get("profile:" + old.id)
            db.companies.save(new)
            if state and ProfilePipeline._description(
                old
            ) == ProfilePipeline._description(new):
                value = state["value"]
                if value.get("status") == "ready" and value.get(
                    "version", ""
                ).startswith(old.profile_version + "|"):
                    db.runtime.save(
                        "profile:" + old.id,
                        {
                            **value,
                            "version": new.profile_version
                            + value["version"][len(old.profile_version) :],
                            "reused_reason": "unchanged_tagging_input",
                        },
                    )
            db.commit()
            updated += 1
    return updated


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data/companies",
    )
    print("Updated:", refresh(parser.parse_args().directory))
