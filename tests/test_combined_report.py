import json
import sys

import pytest

from tests.conftest import generate_combined_report


def test_load_status_check_file_missing(tmp_path):
    assert generate_combined_report.load_status_check_file(str(tmp_path), 7) is None


def test_get_status_message_from_status_file(tmp_path):
    import json

    status = {
        "check_number": 7,
        "status": "FAIL",
        "details": {
            "message": "gate missing",
            "errors": ["Deprecated gate in target: api.openshift.com/foo"],
        },
    }
    (tmp_path / "status-check-7.json").write_text(json.dumps(status))

    assert generate_combined_report.get_status_message(str(tmp_path), 7, "default") == "gate missing"
    loaded = generate_combined_report.load_status_check_file(str(tmp_path), 7)
    assert loaded["details"]["errors"][0].startswith("Deprecated")


def test_fallback_validation_result_preserves_fail(tmp_path):
    import json

    (tmp_path / "status-check-9.json").write_text(
        json.dumps({"status": "FAIL", "details": {"message": "crashed"}})
    )
    assert generate_combined_report.fallback_validation_result(str(tmp_path), 9, default="SKIP") == "FAIL"


def test_fallback_validation_result_skip_when_missing(tmp_path):
    assert generate_combined_report.fallback_validation_result(str(tmp_path), 9, default="SKIP") == "SKIP"


def test_fallback_validation_result_warning_maps_to_warning(tmp_path):
    (tmp_path / "status-check-12.json").write_text(
        json.dumps({"status": "WARN", "details": {"message": "e2e failures"}})
    )
    assert generate_combined_report.fallback_validation_result(str(tmp_path), 12, default="SKIP") == "WARNING"


@pytest.mark.parametrize("current_status", ["FAIL", "ERROR"])
def test_current_ocp_failure_overrides_stale_analyzer_pass(
    current_status, monkeypatch, tmp_path
):
    stale_report = {
        "validation_result": "PASS",
        "ack_check_version": "4.22",
        "summary": {
            "gates_requiring_ack": 0,
            "acknowledged": 0,
            "unacknowledged": 0,
            "ack_file_missing": False,
            "upgrade_ready": True,
        },
        "analysis": {
            "acknowledged_gates": [],
            "unacknowledged_gates": [],
            "extra_acks": [],
        },
        "structure_validation": {"valid": True, "errors": []},
    }
    stale_path = (
        tmp_path
        / "gap-analysis-ocp-gate-ack_4.21_to_4.22_20260101_000000.json"
    )
    stale_path.write_text(json.dumps(stale_report))
    (tmp_path / "status-check-3.json").write_text(
        json.dumps(
            {
                "status": current_status,
                "details": {
                    "message": "CVO ConfigMap fetch failed",
                    "validation_passed": False,
                },
            }
        )
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate-combined-report.py",
            "--baseline",
            "4.21",
            "--target",
            "4.22",
            "--report-dir",
            str(tmp_path),
        ],
    )

    generate_combined_report.main()

    json_path = next(tmp_path.glob("gap-analysis-full_4.21_to_4.22_*.json"))
    generated = json.loads(json_path.read_text())
    assert generated["ocp_gate_ack"]["validation_result"] == "FAIL"
    assert generated["ocp_gate_ack"]["error_message"] == "CVO ConfigMap fetch failed"
    assert generated["ocp_gate_ack"]["summary"]["upgrade_ready"] is False

    html_path = next(tmp_path.glob("gap-analysis-full_4.21_to_4.22_*.html"))
    html = html_path.read_text()
    check_5_summary = html.split(
        '<td><strong>CHECK #5:</strong> OCP Admin Gates</td>', 1
    )[1].split("</tr>", 1)[0]
    assert "❌ FAIL" in check_5_summary
    assert "CVO ConfigMap fetch failed" in check_5_summary
    assert "No gates requiring ack" not in check_5_summary
    check_5_detail = html.split('<h2 id="ocp-gates">', 1)[1].split("<h2", 1)[0]
    assert "❌ Validation Failed" in check_5_detail
    assert "CHECK #5: Admin Gate Acknowledgment - FAILED" in check_5_detail
    assert "CVO ConfigMap fetch failed" in check_5_detail
    assert "✅ Validation Passed" not in check_5_detail
    assert "CHECK #5: Admin Gate Acknowledgment - PASSED" not in check_5_detail
