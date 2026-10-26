"""дополняет профили наблюдаемыми связями и сравнением внутри предоставленного набора"""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

CONTEXT_VERSION = "company-context-v3"


def rows(path, required):
    """читает CSV построчно, не загружая платёжный файл целиком в память"""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        fields = reader.fieldnames or []
        if not set(required).issubset(fields) or len(fields) != len(set(fields)):
            raise ValueError(f"Неверные колонки файла {path.name}")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Неверное количество полей в файле {path.name}")
            yield row


def checksum(path):
    """фиксирует версию входного файла для воспроизводимости признаков"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def enrich_companies(companies, directory: Path):
    """считает признаки только для выбранных компаний без раскрытия идентификаторов физлиц"""
    from app.import_companies import build_company, read_rows

    files = {
        "companies": directory / "df_Uid_data_hack.csv",
        "links": directory / "df_Fid_Uid_link_hack.csv",
        "payments": directory / "df_Uid_payment_hack.csv",
    }
    versions = {key: checksum(path) for key, path in files.items()}
    selected = {company.id: company for company in companies}
    sectors, groups = defaultdict(list), Counter()
    catalog, members = {}, defaultdict(set)
    counts = Counter(
        (row.get("SYNTHETIC_U") or "").strip()
        for _, row in read_rows(files["companies"])
    )
    for number, row in read_rows(files["companies"]):
        if counts[(row.get("SYNTHETIC_U") or "").strip()] != 1:
            continue
        try:
            company = build_company(
                row,
                filename=files["companies"].name,
                checksum=versions["companies"],
                number=number,
            )
        except (ValueError, InvalidOperation):
            continue
        catalog[company.id] = {
            "okved": company.okved_code,
            "region": company.region,
            "group": company.group_id,
        }
        if company.revenue is not None:
            sectors[(company.okved_code or "").split(".")[0]].append(company.revenue)
        if company.group_id and company.group_id not in {"0", "nan", "None"}:
            groups[company.group_id] += 1
            members[company.group_id].add(company.id)
    persons = defaultdict(set)
    for row in rows(files["links"], ("SYNTHETIC_F", "SYNTHETIC_U")):
        person, company_id = (
            row.get("SYNTHETIC_F", "").strip(),
            row.get("SYNTHETIC_U", "").strip(),
        )
        if person and company_id:
            persons[person].add(company_id)
    linked = defaultdict(set)
    for related in persons.values():
        for company_id in related & selected.keys():
            linked[company_id].update(related - {company_id})
    incoming, outgoing = defaultdict(Counter), defaultdict(Counter)
    rejected = 0
    for row in rows(files["payments"], ("PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT")):
        payer, beneficiary = (
            row.get("PAYER", "").strip(),
            row.get("BENEFICIARY", "").strip(),
        )
        if payer not in selected and beneficiary not in selected:
            continue
        try:
            amount = Decimal(row["PAY_AMT"])
            count = Decimal(row["PAY_CNT"])
            if (
                not amount.is_finite()
                or amount < 0
                or not count.is_finite()
                or count < 0
                or count != count.to_integral_value()
            ):
                raise ValueError("Invalid payment")
            if amount > 0 and count == 0:
                raise ValueError("Positive amount without payments")
        except (KeyError, InvalidOperation, ValueError, TypeError):
            rejected += 1
            continue
        if amount == 0 or not payer or not beneficiary or payer == beneficiary:
            continue
        if payer in selected:
            outgoing[payer][beneficiary] += amount
        if beneficiary in selected:
            incoming[beneficiary][payer] += amount
    if versions != {key: checksum(path) for key, path in files.items()}:
        raise ValueError("Company context files changed during processing")
    result = []
    for company in companies:
        values = {
            "market_share_status": "Не определена: нет подтверждённого полного размера рынка",
            "payment_data_scope": "Только предоставленная выборка платежей, период и полнота неизвестны; отсутствие записей не означает отсутствие платежей",
            "linked_companies_in_dataset": len(linked[company.id]),
            "group_companies_in_dataset": groups.get(company.group_id),
        }
        for relation, ids in (
            ("linked", linked[company.id]),
            ("group", members[company.group_id] - {company.id}),
        ):
            known = [catalog[id] for id in ids if id in catalog]
            values[f"{relation}_company_sectors"] = dict(
                Counter(item["okved"] for item in known if item["okved"]).most_common(5)
            )
            values[f"{relation}_company_regions"] = dict(
                Counter(item["region"] for item in known if item["region"]).most_common(
                    5
                )
            )
        peers = sectors[(company.okved_code or "").split(".")[0]]
        if peers and company.revenue is not None and company.okved_code:
            rank = 1 + sum(value > company.revenue for value in peers)
            values["industry_position_in_dataset"] = (
                f"Место по выручке {rank} из {len(peers)} компаний той же группы ОКВЭД в предоставленных данных; это не позиция на всём рынке"
            )
        for direction, data in (
            ("incoming", incoming[company.id]),
            ("outgoing", outgoing[company.id]),
        ):
            values[f"payment_{direction}_counterparties"] = len(data)
            if data:
                total = sum(data.values())
                industries, regions = Counter(), Counter()
                covered = Decimal(0)
                group_amount = Decimal(0)
                for counterpart, amount in data.items():
                    details = catalog.get(counterpart)
                    if details is None:
                        continue
                    covered += amount
                    if details["okved"]:
                        industries[details["okved"]] += amount
                    if details["region"]:
                        regions[details["region"]] += amount
                    if counterpart in members[company.group_id]:
                        group_amount += amount
                for name, amounts in (("sectors", industries), ("regions", regions)):
                    values[f"payment_{direction}_{name}"] = {
                        key: round(float(amount / total * 100), 2)
                        for key, amount in amounts.most_common(5)
                    }
                values[f"payment_{direction}_known_share_pct"] = round(
                    float(covered / total * 100), 2
                )
                values[f"payment_{direction}_group_share_pct"] = round(
                    float(group_amount / total * 100), 2
                )
                values[f"payment_{direction}_largest_share_pct"] = float(
                    round(max(data.values()) / sum(data.values()) * 100, 2)
                )
        profile = {
            **{
                key: value
                for key, value in company.profile_json.items()
                if not key.startswith(
                    (
                        "payment_",
                        "linked_",
                        "group_company",
                        "group_companies",
                        "_context_",
                    )
                )
                and key not in {"market_share_status", "industry_position_in_dataset"}
            },
            **values,
            "_context_sources": {
                key: {"file": files[key].name, "sha256": value}
                for key, value in versions.items()
            },
            "_context_rejected_payments": rejected,
        }
        version = hashlib.sha256(
            json.dumps(profile, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        result.append(
            company.model_copy(
                update={
                    "profile_json": profile,
                    "profile_version": CONTEXT_VERSION + ":" + version,
                }
            )
        )
    return result
