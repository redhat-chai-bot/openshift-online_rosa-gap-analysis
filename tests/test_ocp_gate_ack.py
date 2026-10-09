import errno
import json
import socket
import ssl
import sys
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from tests.conftest import gap_ocp_gate_ack


def _status_data(report_dir):
    return json.loads((report_dir / "status-check-3.json").read_text())


@pytest.mark.parametrize(
    "failure",
    [
        URLError("Temporary failure in name resolution"),
        URLError(
            socket.gaierror(
                socket.EAI_AGAIN,
                "Temporary failure in name resolution",
            )
        ),
        ConnectionResetError(errno.ECONNRESET, "Connection reset by peer"),
        ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused"),
        HTTPError(
            "https://raw.githubusercontent.com/example/config.yaml",
            503,
            "unavailable",
            {},
            None,
        ),
        HTTPError(
            "https://raw.githubusercontent.com/example/config.yaml",
            408,
            "request timeout",
            {},
            None,
        ),
        HTTPError(
            "https://raw.githubusercontent.com/example/config.yaml",
            429,
            "too many requests",
            {},
            None,
        ),
    ],
    ids=[
        "dns",
        "typed-eai-again",
        "direct-connection-reset",
        "direct-connection-refused",
        "http-503",
        "http-408",
        "http-429",
    ],
)
def test_fetch_yaml_retries_transient_failure_then_succeeds(monkeypatch, failure):
    response = Mock()
    response.read.return_value = b"data:\n  gate: acknowledged\n"
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    urlopen = Mock(side_effect=[failure, response])
    sleep = Mock()

    monkeypatch.setattr(gap_ocp_gate_ack, "urlopen", urlopen)
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", sleep)

    result = gap_ocp_gate_ack.fetch_yaml_from_github(
        "https://raw.githubusercontent.com/example/config.yaml",
        retry_delays=(2,),
    )

    assert result == {"data": {"gate": "acknowledged"}}
    assert urlopen.call_count == 2
    sleep.assert_called_once_with(2)


@pytest.mark.parametrize(
    "dns_error",
    [
        socket.gaierror(socket.EAI_NONAME, "Name or service not known"),
        socket.gaierror(socket.EAI_FAIL, "Non-recoverable failure in name resolution"),
    ],
    ids=["eai-noname", "eai-fail"],
)
def test_permanent_typed_dns_failure_is_not_retried(
    monkeypatch,
    tmp_path,
    dns_error,
):
    urlopen = Mock(side_effect=URLError(dns_error))
    sleep = Mock()
    monkeypatch.setattr(
        gap_ocp_gate_ack,
        "resolve_versions_with_retry",
        Mock(return_value=("4.21.20", "4.22.0-rc.1")),
    )
    monkeypatch.setattr(gap_ocp_gate_ack, "urlopen", urlopen)
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", sleep)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gap-ocp-gate-ack.py",
            "--baseline",
            "4.21.20",
            "--target",
            "4.22.0-rc.1",
            "--report-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        gap_ocp_gate_ack.main()

    assert exit_info.value.code == 1
    assert urlopen.call_count == 1
    sleep.assert_not_called()
    status = _status_data(tmp_path)
    assert status["status"] == "FAIL"
    assert status["exit_code"] == 1
    assert status["details"]["failure_stage"] == "YAML fetch"
    assert status["details"]["attempts"] == 1
    assert status["details"]["retries"] == []
    assert status["details"]["validation_passed"] is False


def test_permanent_direct_oserror_is_not_retried(monkeypatch, tmp_path):
    urlopen = Mock(side_effect=PermissionError(errno.EACCES, "Permission denied"))
    sleep = Mock()
    monkeypatch.setattr(
        gap_ocp_gate_ack,
        "resolve_versions_with_retry",
        Mock(return_value=("4.21.20", "4.22.0-rc.1")),
    )
    monkeypatch.setattr(gap_ocp_gate_ack, "urlopen", urlopen)
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", sleep)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gap-ocp-gate-ack.py",
            "--baseline",
            "4.21.20",
            "--target",
            "4.22.0-rc.1",
            "--report-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        gap_ocp_gate_ack.main()

    assert exit_info.value.code == 1
    assert urlopen.call_count == 1
    sleep.assert_not_called()
    status = _status_data(tmp_path)
    assert status["status"] == "FAIL"
    assert status["exit_code"] == 1
    assert status["details"]["attempts"] == 1
    assert status["details"]["retries"] == []
    assert status["details"]["validation_passed"] is False


def test_cvo_source_404_is_structured_failure(monkeypatch, tmp_path):
    cvo_url = gap_ocp_gate_ack.CVO_ADMIN_GATE_URL.format(version="4.21")
    urlopen = Mock(side_effect=HTTPError(cvo_url, 404, "Not Found", {}, None))
    sleep = Mock()
    monkeypatch.setattr(
        gap_ocp_gate_ack,
        "resolve_versions_with_retry",
        Mock(return_value=("4.21.20", "4.22.0-rc.1")),
    )
    monkeypatch.setattr(gap_ocp_gate_ack, "urlopen", urlopen)
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", sleep)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gap-ocp-gate-ack.py",
            "--baseline",
            "4.21.20",
            "--target",
            "4.22.0-rc.1",
            "--report-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        gap_ocp_gate_ack.main()

    assert exit_info.value.code == 1
    assert urlopen.call_count == 1
    sleep.assert_not_called()
    status = _status_data(tmp_path)
    assert status["status"] == "FAIL"
    assert status["exit_code"] == 1
    assert status["details"]["failure_stage"] == "YAML fetch"
    assert status["details"]["url"] == cvo_url
    assert status["details"]["attempts"] == 1
    assert status["details"]["retries"] == []
    assert status["details"]["validation_passed"] is False


def test_optional_mcc_404_preserves_absence_semantics(monkeypatch):
    url = "https://raw.githubusercontent.com/example/optional.yaml"
    urlopen = Mock(side_effect=HTTPError(url, 404, "Not Found", {}, None))
    sleep = Mock()
    monkeypatch.setattr(gap_ocp_gate_ack, "urlopen", urlopen)
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", sleep)

    result = gap_ocp_gate_ack.fetch_yaml_from_github(url, allow_missing=True)

    assert result is None
    assert urlopen.call_count == 1
    sleep.assert_not_called()


def test_version_resolution_success_returns_once_and_restores_logger(monkeypatch):
    expected_versions = ("4.21.20", "4.22.0-rc.1")
    resolver = Mock(return_value=expected_versions)
    sleep = Mock()
    original_log_error = gap_ocp_gate_ack.openshift_releases.log_error
    monkeypatch.setattr(
        gap_ocp_gate_ack.openshift_releases,
        "resolve_gap_versions",
        resolver,
    )
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", sleep)

    result = gap_ocp_gate_ack.resolve_versions_with_retry(
        version="4.22",
        baseline=None,
        target=None,
    )

    assert result == expected_versions
    resolver.assert_called_once_with(
        version="4.22",
        baseline=None,
        target=None,
    )
    sleep.assert_not_called()
    assert gap_ocp_gate_ack.openshift_releases.log_error is original_log_error


def test_successful_main_preserves_report_and_status_schema(monkeypatch, tmp_path):
    expected_versions = ("4.21.20", "4.22.0-rc.1")
    resolver = Mock(return_value=expected_versions)
    sleep = Mock()
    original_log_error = gap_ocp_gate_ack.openshift_releases.log_error
    monkeypatch.setattr(
        gap_ocp_gate_ack.openshift_releases,
        "resolve_gap_versions",
        resolver,
    )
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", sleep)
    monkeypatch.setattr(gap_ocp_gate_ack, "fetch_admin_gates", Mock(return_value={}))
    monkeypatch.setattr(
        gap_ocp_gate_ack,
        "fetch_admin_acks",
        Mock(return_value=(None, None)),
    )
    monkeypatch.setattr(
        gap_ocp_gate_ack,
        "validate_ocp_acknowledgment_structure",
        Mock(
            return_value={
                "valid": True,
                "errors": [],
                "warnings": [],
                "config_exists": False,
                "ack_file_exists": False,
                "actual_baseline": None,
            }
        ),
    )
    monkeypatch.setattr(
        gap_ocp_gate_ack,
        "check_ocm_version_gates",
        Mock(return_value={"status": "PASS", "message": "available", "gates": []}),
    )
    monkeypatch.setenv("GAP_FULL_REPORT", "1")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gap-ocp-gate-ack.py",
            "--version",
            "4.22",
            "--report-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        gap_ocp_gate_ack.main()

    assert exit_info.value.code == 0
    resolver.assert_called_once_with(version="4.22", baseline=None, target=None)
    sleep.assert_not_called()
    assert gap_ocp_gate_ack.openshift_releases.log_error is original_log_error

    report_path = next(
        tmp_path.glob("gap-analysis-ocp-gate-ack_4.21_to_4.22_*.json")
    )
    report = json.loads(report_path.read_text())
    assert report["validation_result"] == "PASS"
    assert (report["baseline_full"], report["target_full"]) == expected_versions
    assert report["summary"] == {
        "gates_requiring_ack": 0,
        "acknowledged": 0,
        "unacknowledged": 0,
        "extra_acks": 0,
        "ack_file_missing": True,
        "upgrade_ready": True,
    }

    status = _status_data(tmp_path)
    assert status["status"] == "PASS"
    assert status["exit_code"] == 0
    assert status["details"] == {
        "gates_count": 0,
        "acked_count": 0,
        "unacked_count": 0,
        "validation_passed": True,
        "message": "no gates requiring acknowledgment",
    }


def test_version_resolution_failure_writes_structured_status(monkeypatch, tmp_path):
    resolver = Mock()

    def fail_resolution(**_kwargs):
        resolver()
        gap_ocp_gate_ack.openshift_releases.log_error(
            "Failed to fetch GA dates from Sippy API: "
            "<urlopen error Temporary failure in name resolution>"
        )
        raise SystemExit(1)

    monkeypatch.setattr(
        gap_ocp_gate_ack.openshift_releases,
        "resolve_gap_versions",
        fail_resolution,
    )
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", Mock())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gap-ocp-gate-ack.py",
            "--version",
            "4.22",
            "--report-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        gap_ocp_gate_ack.main()

    assert exit_info.value.code == 1
    assert resolver.call_count == 3
    status = _status_data(tmp_path)
    assert status["check_number"] == 3
    assert status["check_name"] == "OCP Admin Gate Acknowledgments"
    assert status["status"] == "FAIL"
    assert status["exit_code"] == 1
    assert status["details"]["failure_stage"] == "version resolution"
    assert status["details"]["url"] == gap_ocp_gate_ack.openshift_releases.SIPPY_API
    assert status["details"]["host"] == "sippy.dptools.openshift.org"
    assert status["details"]["attempts"] == 3
    assert len(status["details"]["retries"]) == 2
    assert "Temporary failure in name resolution" in status["details"]["errors"][0]


def test_direct_accepted_stream_reset_does_not_report_sippy(monkeypatch, tmp_path):
    requested_urls = []

    def reset_accepted_stream(req, timeout):
        requested_urls.append(req.full_url)
        if req.full_url == gap_ocp_gate_ack.openshift_releases.SIPPY_API:
            response = Mock()
            response.read.return_value = b'{"ga_dates": {"4.21": "2025-06-24"}}'
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            return response
        if req.full_url == gap_ocp_gate_ack.openshift_releases.ACCEPTED_STREAMS_API:
            raise ConnectionResetError(errno.ECONNRESET, "Connection reset by peer")
        pytest.fail(f"Unexpected resolver URL: {req.full_url}")

    monkeypatch.setattr(
        gap_ocp_gate_ack.openshift_releases,
        "urlopen",
        reset_accepted_stream,
    )
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", Mock())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gap-ocp-gate-ack.py",
            "--version",
            "4.22",
            "--report-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        gap_ocp_gate_ack.main()

    assert exit_info.value.code == 1
    assert requested_urls == [
        gap_ocp_gate_ack.openshift_releases.SIPPY_API,
        gap_ocp_gate_ack.openshift_releases.ACCEPTED_STREAMS_API,
    ] * 3
    status = _status_data(tmp_path)
    assert status["details"]["failure_stage"] == "version resolution"
    assert status["details"]["url"] is None
    assert status["details"]["host"] is None
    assert status["details"]["attempts"] == 3
    assert all(retry["url"] is None for retry in status["details"]["retries"])


@pytest.mark.parametrize(
    "message, expected_url",
    [
        (
            "Failed to fetch accepted release streams: HTTP Error 404: Not Found",
            gap_ocp_gate_ack.openshift_releases.ACCEPTED_STREAMS_API,
        ),
        (
            "No version found for 4.22 (checked candidate, CI, nightly)",
            gap_ocp_gate_ack.openshift_releases.ACCEPTED_STREAMS_API,
        ),
        (
            "Failed to fetch GA dates from Sippy API: "
            "Expecting value: line 1 column 1 (char 0)",
            gap_ocp_gate_ack.openshift_releases.SIPPY_API,
        ),
    ],
    ids=["http-404", "accepted-stream-selection", "json-decode"],
)
def test_version_resolution_permanent_failure_is_not_retried(
    monkeypatch,
    tmp_path,
    message,
    expected_url,
):
    resolver = Mock()

    def fail_resolution(**_kwargs):
        resolver()
        gap_ocp_gate_ack.openshift_releases.log_error(message)
        raise SystemExit(1)

    sleep = Mock()
    monkeypatch.setattr(
        gap_ocp_gate_ack.openshift_releases,
        "resolve_gap_versions",
        fail_resolution,
    )
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", sleep)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gap-ocp-gate-ack.py",
            "--version",
            "4.22",
            "--report-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        gap_ocp_gate_ack.main()

    assert exit_info.value.code == 1
    assert resolver.call_count == 1
    sleep.assert_not_called()
    status = _status_data(tmp_path)
    assert status["status"] == "FAIL"
    assert status["exit_code"] == 1
    assert status["details"]["failure_stage"] == "version resolution"
    assert status["details"]["url"] == expected_url
    if "checked candidate" in message:
        assert status["details"]["url"] != (
            gap_ocp_gate_ack.openshift_releases.RELEASE_STREAM_BASE
        )
    assert status["details"]["attempts"] == 1
    assert status["details"]["retries"] == []
    assert status["details"]["validation_passed"] is False


def test_tls_certificate_failure_is_not_retried(monkeypatch, tmp_path):
    tls_error = ssl.SSLCertVerificationError(
        1,
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
    )
    urlopen = Mock(side_effect=URLError(tls_error))
    sleep = Mock()
    monkeypatch.setattr(
        gap_ocp_gate_ack,
        "resolve_versions_with_retry",
        Mock(return_value=("4.21.20", "4.22.0-rc.1")),
    )
    monkeypatch.setattr(gap_ocp_gate_ack, "urlopen", urlopen)
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", sleep)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gap-ocp-gate-ack.py",
            "--baseline",
            "4.21.20",
            "--target",
            "4.22.0-rc.1",
            "--report-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        gap_ocp_gate_ack.main()

    assert exit_info.value.code == 1
    assert urlopen.call_count == 1
    sleep.assert_not_called()
    status = _status_data(tmp_path)
    assert status["status"] == "FAIL"
    assert status["exit_code"] == 1
    assert status["details"]["failure_stage"] == "YAML fetch"
    assert status["details"]["url"] == gap_ocp_gate_ack.CVO_ADMIN_GATE_URL.format(
        version="4.21"
    )
    assert status["details"]["host"] == "raw.githubusercontent.com"
    assert status["details"]["attempts"] == 1
    assert status["details"]["retries"] == []
    assert status["details"]["validation_passed"] is False


def test_managed_config_fetch_failure_writes_structured_status(monkeypatch, tmp_path):
    url = (
        "https://raw.githubusercontent.com/openshift/managed-cluster-config/"
        "master/deploy/osd-cluster-acks/ocp/4.22/admin-ack.yaml"
    )
    monkeypatch.setattr(
        gap_ocp_gate_ack,
        "resolve_versions_with_retry",
        Mock(return_value=("4.21.20", "4.22.0-rc.1")),
    )
    monkeypatch.setattr(gap_ocp_gate_ack, "fetch_admin_gates", Mock(return_value={}))
    urlopen = Mock(side_effect=URLError("[Errno -3] Temporary failure in name resolution"))
    monkeypatch.setattr(gap_ocp_gate_ack, "urlopen", urlopen)
    monkeypatch.setattr(gap_ocp_gate_ack.time, "sleep", Mock())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gap-ocp-gate-ack.py",
            "--baseline",
            "4.21.20",
            "--target",
            "4.22.0-rc.1",
            "--report-dir",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        gap_ocp_gate_ack.main()

    assert exit_info.value.code == 1
    status = _status_data(tmp_path)
    assert status["status"] == "FAIL"
    assert status["details"]["failure_stage"] == "YAML fetch"
    assert status["details"]["url"] == url
    assert status["details"]["host"] == "raw.githubusercontent.com"
    assert status["details"]["attempts"] == 3
    assert [retry["delay_seconds"] for retry in status["details"]["retries"]] == [2, 4]
    assert status["details"]["validation_passed"] is False
    assert urlopen.call_count == 3
