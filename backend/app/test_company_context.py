"""проверяет происхождение и ограничения признаков из исходных CSV"""

import asyncio
import csv
import json
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.import_companies import COLUMNS, build_company, import_companies
from app.schemas.tagging import ProfileForTagging
from app.services.ai_agents.client import JsonClient
from app.services.ai_agents.profile_tagger import ProfileTagger
from app.services.company_context import enrich_companies


@pytest.mark.parametrize("status,expected", [(503, 2), (429, 2), (401, 1), (400, 1)])
def test_client_retries_only_transient_failures(status, expected):
    client = JsonClient(transport=lambda *args: None)
    cause = httpx.HTTPStatusError(
        "provider failure",
        request=httpx.Request("POST", "https://example.org"),
        response=httpx.Response(status),
    )
    error = RuntimeError("Model provider unavailable")
    error.__cause__ = cause
    client._ask_once = AsyncMock(side_effect=[error, "ready"])
    with patch("app.services.ai_agents.client.asyncio.sleep", new_callable=AsyncMock):
        if expected == 2:
            assert asyncio.run(client.ask("instruction", {}, object)) == "ready"
        else:
            with pytest.raises(RuntimeError):
                asyncio.run(client.ask("instruction", {}, object))
    assert client._ask_once.call_count == expected


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def company_files(tmp_path):
    rows = []
    for number, revenue in ((1, "20000000000"), (2, "30000000000"), (3, "15000000000")):
        row = dict.fromkeys(COLUMNS, "")
        row.update(
            SYNTHETIC_U=f"U_{number}",
            REVENUE_COMPANY=revenue,
            MAINOKVED_CODE="46.90",
            GROUP_ID="G1",
        )
        rows.append(row)
    write_csv(tmp_path / "df_Uid_data_hack.csv", COLUMNS, rows)
    write_csv(
        tmp_path / "df_Fid_Uid_link_hack.csv",
        ["SYNTHETIC_F", "SYNTHETIC_U"],
        [{"SYNTHETIC_F": "F_1", "SYNTHETIC_U": id} for id in ["U_1", "U_2", "U_2"]],
    )
    write_csv(
        tmp_path / "df_Uid_payment_hack.csv",
        ["PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT"],
        [
            {"PAYER": payer, "BENEFICIARY": "U_1", "PAY_AMT": amount, "PAY_CNT": count}
            for payer, amount, count in [
                ("U_2", "60", "1"),
                ("U_2", "20", "1"),
                ("U_3", "20", "1"),
                ("U_1", "1000", "1"),
                ("U_3", "NaN", "1"),
                ("U_3", "500", "0"),
            ]
        ],
    )
    return tmp_path, build_company(
        rows[0], filename="source.csv", checksum="hash", number=2
    )


def test_context_preserves_scope_and_provenance(company_files):
    path, company = company_files
    enriched = enrich_companies([company], path)[0]
    values = enriched.profile_json
    assert values["payment_incoming_counterparties"] == 2
    assert values["payment_incoming_largest_share_pct"] == 80
    assert values["payment_incoming_sectors"] == {"46.90": 100}
    assert values["payment_incoming_group_share_pct"] == 100
    assert values["payment_incoming_known_share_pct"] == 100
    assert values["linked_company_sectors"] == {"46.90": 1}
    assert values["group_company_sectors"] == {"46.90": 2}
    assert values["payment_outgoing_counterparties"] == 0
    assert "payment_outgoing_largest_share_pct" not in values
    assert values["linked_companies_in_dataset"] == 1
    assert values["group_companies_in_dataset"] == 3
    assert "2 из 3" in values["industry_position_in_dataset"]
    assert values["_context_rejected_payments"] == 2
    assert len(values["_context_sources"]["payments"]["sha256"]) == 64
    assert "F_1" not in enriched.model_dump_json()
    assert enriched == enrich_companies([company], path)[0]
    assert enriched == enrich_companies([enriched], path)[0]
    assert enriched.profile_version != company.profile_version


def test_refresh_removes_disappeared_payment_features(company_files):
    path, company = company_files
    enriched = enrich_companies([company], path)[0]
    write_csv(
        path / "df_Uid_payment_hack.csv",
        ["PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT"],
        [],
    )
    refreshed = enrich_companies([enriched], path)[0]
    assert refreshed.profile_json["payment_incoming_counterparties"] == 0
    assert "payment_incoming_sectors" not in refreshed.profile_json
    assert "payment_incoming_largest_share_pct" not in refreshed.profile_json
    assert refreshed == enrich_companies([refreshed], path)[0]


def test_missing_headers_do_not_become_zero_payments(company_files):
    path, company = company_files
    (path / "df_Uid_payment_hack.csv").write_text("wrong;header\n1;2", encoding="utf-8")
    with pytest.raises(ValueError, match="колонки"):
        enrich_companies([company], path)


def test_unknown_counterparty_keeps_its_share_in_denominator(company_files):
    path, company = company_files
    with (path / "df_Uid_payment_hack.csv").open("a", encoding="utf-8") as stream:
        stream.write("UNKNOWN;U_1;100;1\n")
    result = enrich_companies([company], path)[0].profile_json
    assert result["payment_incoming_known_share_pct"] == 50
    assert result["payment_incoming_sectors"] == {"46.90": 50}
    assert result["payment_incoming_group_share_pct"] == 50


def test_target_scale_excludes_boundary(company_files):
    path, _ = company_files
    result = import_companies(
        path / "df_Uid_data_hack.csv",
        limit=2,
        check_only=True,
        min_revenue=Decimal(15000000000),
        output_dir=path / "result",
    )
    assert set(result["company_ids"]) == {"U_1", "U_2"}
    assert result["below_min_revenue"] == 1


def test_tagger_corrects_unknown_code_once(tmp_path):
    catalog = tmp_path / "tags.json"
    catalog.write_text(
        json.dumps(
            {
                "business": {"Торговля": "biz_trade"},
                "region": {"Москва": "reg_77"},
                "city": {"Москва": "mos"},
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def transport(messages):
        calls.append(messages)
        return json.dumps(
            {
                "tags": [
                    {
                        "id": "invented" if len(calls) == 1 else "biz_trade",
                        "confidence": 1,
                    }
                ],
                "geography": {},
            }
        )

    result = ProfileTagger(catalog_path=catalog, transport=transport).tag(
        ProfileForTagging(city="", text="Торговля")
    )
    assert result.tags[0].id == "biz_trade"
    assert len(calls) == 2
    assert "validation_error" in calls[1][1]["content"]
