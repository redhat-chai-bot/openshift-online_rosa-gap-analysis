import socket
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, call, patch

import pytest

from ack_validation import fetch_yaml_from_url
from common import fetch_url
from openshift_releases import fetch_accepted_streams, fetch_sippy_ga_dates, get_latest_dev_nightly_version
from prow_artifacts import fetch_json_url
from tests.conftest import gap_ocp_gate_ack


def _response(payload):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = payload
    return response


@patch("openshift_releases.get_latest_ga_version", return_value="4.21")
@patch("common.time.sleep")
@patch("common.urlopen")
@pytest.mark.parametrize(
    ("fetcher", "payload", "expected", "timeout"),
    [
        (
            fetch_sippy_ga_dates,
            b'{"ga_dates": {"4.21": "2026-07-17"}}',
            {"4.21": "2026-07-17"},
            10,
        ),
        (
            fetch_accepted_streams,
            b'{"4-stable": ["4.21.18"], "4-dev-preview": ["4.22.0-rc.0"]}',
            {"4-stable": ["4.21.18"], "4-dev-preview": ["4.22.0-rc.0"]},
            10,
        ),
        (
            get_latest_dev_nightly_version,
            b'{"name": "4.22.0-0.nightly-2026-10-07-000000"}',
            "4.22.0-0.nightly-2026-10-07-000000",
            10,
        ),
        (
            lambda: fetch_yaml_from_url("https://raw.githubusercontent.com/example/config.yaml"),
            b"baseline: 4.20\n",
            {"baseline": 4.20},
            30,
        ),
        (
            lambda: gap_ocp_gate_ack.fetch_yaml_from_github(
                "https://raw.githubusercontent.com/example/admin-gates.yaml"
            ),
            b"data:\n  gate: acknowledged\n",
            {"data": {"gate": "acknowledged"}},
            30,
        ),
        (
            lambda: fetch_json_url("https://storage.googleapis.com/example/metadata.json"),
            b'{"status": "ok"}',
            {"status": "ok"},
            45,
        ),
    ],
    ids=("sippy", "accepted-streams", "nightly", "raw-github", "ocp-admin-gate", "prow-gcs"),
)
def test_per_check_fetches_retry_transient_dns_failure(
    mock_urlopen, mock_sleep, _mock_latest_ga, capsys, fetcher, payload, expected, timeout
):
    dns_error = URLError(socket.gaierror(-2, "Name or service not known"))
    mock_urlopen.side_effect = [dns_error, _response(payload)]

    assert fetcher() == expected

    assert mock_urlopen.call_count == 2
    assert all(item.kwargs["timeout"] == timeout for item in mock_urlopen.call_args_list)
    mock_sleep.assert_called_once_with(2)
    stderr = capsys.readouterr().err
    assert "attempt 1/3" in stderr
    assert "Name or service not known" in stderr


@patch("common.time.sleep")
@patch("common.urlopen")
def test_fetch_url_succeeds_on_first_attempt(mock_urlopen, mock_sleep):
    mock_urlopen.return_value = _response(b"response body")

    assert fetch_url("https://example.test/data", timeout=7) == b"response body"

    mock_urlopen.assert_called_once()
    request = mock_urlopen.call_args.args[0]
    assert request.full_url == "https://example.test/data"
    assert request.get_header("User-agent") == "gap-analysis-script"
    assert mock_urlopen.call_args.kwargs["timeout"] == 7
    mock_sleep.assert_not_called()


@patch("common.time.sleep")
@patch("common.urlopen")
@pytest.mark.parametrize(
    ("transient_error", "expected_exception", "message"),
    [
        (
            URLError("temporary failure in name resolution"),
            URLError,
            "temporary failure in name resolution",
        ),
        (
            HTTPError("https://example.test/data", 503, "Service Unavailable", {}, None),
            HTTPError,
            "HTTP Error 503: Service Unavailable",
        ),
        (TimeoutError("timed out"), TimeoutError, "timed out"),
    ],
    ids=("dns", "http-503", "timeout"),
)
def test_fetch_url_raises_after_transient_failures_are_exhausted(
    mock_urlopen, mock_sleep, capsys, transient_error, expected_exception, message
):
    mock_urlopen.side_effect = transient_error

    with pytest.raises(expected_exception, match=message):
        fetch_url("https://example.test/data", timeout=5, max_retries=2, retry_delay=1)

    assert mock_urlopen.call_count == 3
    assert mock_sleep.call_args_list == [call(1), call(2)]
    stderr = capsys.readouterr().err
    assert "https://example.test/data" in stderr
    assert "after 3 attempts" in stderr
    assert "timeout=5s" in stderr


@patch("common.time.sleep")
@patch("common.urlopen")
def test_fetch_url_with_zero_retries_makes_one_attempt(mock_urlopen, mock_sleep):
    mock_urlopen.side_effect = TimeoutError("timed out")

    with pytest.raises(TimeoutError, match="timed out"):
        fetch_url("https://example.test/data", max_retries=0)

    mock_urlopen.assert_called_once()
    mock_sleep.assert_not_called()


@patch("common.urlopen")
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_retries": -1}, "max_retries must be a non-negative integer"),
        ({"max_retries": 1.5}, "max_retries must be a non-negative integer"),
        ({"max_retries": True}, "max_retries must be a non-negative integer"),
        ({"retry_delay": -1}, "retry_delay must be non-negative"),
    ],
    ids=("negative-retries", "non-integer-retries", "boolean-retries", "negative-delay"),
)
def test_fetch_url_rejects_invalid_retry_controls(mock_urlopen, kwargs, message):
    with pytest.raises(ValueError, match=message):
        fetch_url("https://example.test/data", **kwargs)

    mock_urlopen.assert_not_called()


@patch("common.time.sleep")
@patch("common.urlopen")
def test_fetch_url_does_not_retry_permanent_http_error(mock_urlopen, mock_sleep):
    mock_urlopen.side_effect = HTTPError("https://example.test/missing", 404, "Not Found", {}, None)

    with pytest.raises(HTTPError) as error:
        fetch_url("https://example.test/missing")

    assert error.value.code == 404
    mock_urlopen.assert_called_once()
    mock_sleep.assert_not_called()


@patch("common.time.sleep")
@patch("common.urlopen")
def test_ocp_admin_gate_fetch_maps_404_to_none(mock_urlopen, mock_sleep):
    mock_urlopen.side_effect = HTTPError(
        "https://raw.githubusercontent.com/example/admin-gates.yaml",
        404,
        "Not Found",
        {},
        None,
    )

    result = gap_ocp_gate_ack.fetch_yaml_from_github("https://raw.githubusercontent.com/example/admin-gates.yaml")

    assert result is None
    mock_urlopen.assert_called_once()
    mock_sleep.assert_not_called()
