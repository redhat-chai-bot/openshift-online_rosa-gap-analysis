import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from summary_artifacts import artifact_urls, print_artifacts


JOB = "periodic-ci-openshift-online-rosa-gap-analysis-main-periodics-nightly-5-0"
BUILD_ID = "2109917462479769600"
JOB_PATH = f"test-platform-results-public/logs/{JOB}/{BUILD_ID}"
PUBLIC_BASE = f"https://gcs.ci.openshift.org/gcs/{JOB_PATH}"
REPORT_NAME = "gap-analysis-full_4.22.18_to_5.0.0-rc.6_20261013_080815.html"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ci_environment(tmp_path):
    artifact_dir = tmp_path / "logs" / "artifacts"
    artifact_dir.mkdir(parents=True)
    return {
        "JOB_NAME": JOB,
        "BUILD_ID": BUILD_ID,
        "JOB_NAME_SAFE": "nightly-5-0",
        "HOSTNAME": "nightly-5-0-5-0-gap-analysis",
        "ARTIFACT_DIR": str(artifact_dir),
        "JOB_SPEC": json.dumps({
            "type": "periodic",
            "job": JOB,
            "buildid": BUILD_ID,
            "decoration_config": {
                "gcs_configuration": {
                    "bucket": "test-platform-results-public",
                    "path_strategy": "single",
                },
            },
        }),
    }


def test_real_periodic_nested_artifact_path(ci_environment, capsys):
    report_dir = Path(ci_environment["ARTIFACT_DIR"]) / "rosa-gap-analysis-reports"
    report_dir.mkdir()
    (report_dir / REPORT_NAME).touch()
    print_artifacts(str(report_dir), ci_environment)
    output = capsys.readouterr().out
    expected_report_url = (
        f"{PUBLIC_BASE}/artifacts/nightly-5-0/5-0-gap-analysis/artifacts/rosa-gap-analysis-reports/{REPORT_NAME}"
    )
    assert expected_report_url in output
    assert f"- Build log: {PUBLIC_BASE}/build-log.txt" in output
    assert f"- Reports directory: {report_dir}/" in output


def test_local_paths_without_metadata(tmp_path, capsys):
    (tmp_path / "report.html").touch()
    print_artifacts(str(tmp_path), {"BUILD_LOG": "local-build.log"})
    output = capsys.readouterr().out
    assert str(tmp_path / "report.html") in output
    assert "- Build log: local-build.log" in output
    assert "https://" not in output
    assert "job123" not in output and "build1234" not in output


@pytest.mark.parametrize("missing", ["JOB_SPEC", "ARTIFACT_DIR", "JOB_NAME_SAFE", "HOSTNAME"])
def test_incomplete_environment_is_local_only(ci_environment, missing, capsys):
    report_dir = Path(ci_environment["ARTIFACT_DIR"]) / "rosa-gap-analysis-reports"
    report_dir.mkdir()
    (report_dir / "report.html").touch()
    del ci_environment[missing]
    print_artifacts(str(report_dir), ci_environment)
    output = capsys.readouterr().out
    assert str(report_dir / "report.html") in output
    assert "https://" not in output


@pytest.mark.parametrize("spec", ["{", "null", "[]", "{}", '{"decoration_config": null}'])
def test_invalid_job_spec_is_local_only(ci_environment, spec):
    ci_environment["JOB_SPEC"] = spec
    assert artifact_urls(ci_environment["ARTIFACT_DIR"], ci_environment) is None


@pytest.mark.parametrize("field", ["job", "buildid", "bucket", "path_strategy"])
def test_incomplete_job_spec_is_local_only(ci_environment, field):
    spec = json.loads(ci_environment["JOB_SPEC"])
    source = spec if field in ("job", "buildid") else spec["decoration_config"]["gcs_configuration"]
    del source[field]
    ci_environment["JOB_SPEC"] = json.dumps(spec)
    assert artifact_urls(ci_environment["ARTIFACT_DIR"], ci_environment) is None


@pytest.mark.parametrize("field,value", [
    ("HOSTNAME", "unrelated-pod"),
    ("HOSTNAME", "nightly-5-0-" + "a" * 60),
    ("JOB_NAME_SAFE", "nightly_5_0"),
    ("JOB_NAME", "another-job"),
    ("BUILD_ID", "another-build"),
])
def test_ambiguous_metadata_is_local_only(ci_environment, field, value):
    ci_environment[field] = value
    assert artifact_urls(ci_environment["ARTIFACT_DIR"], ci_environment) is None


def test_reports_outside_upload_directory_are_local_only(ci_environment, tmp_path):
    assert artifact_urls(str(tmp_path / "outside"), ci_environment) is None


def test_report_paths_are_url_encoded(ci_environment):
    report_dir = str(Path(ci_environment["ARTIFACT_DIR"]) / "reports with spaces")
    assert artifact_urls(report_dir, ci_environment)[0].endswith("/reports%20with%20spaces")


def test_report_filenames_are_url_encoded(ci_environment, capsys):
    report_dir = Path(ci_environment["ARTIFACT_DIR"]) / "reports"
    report_dir.mkdir()
    (report_dir / "report #1.html").touch()
    print_artifacts(str(report_dir), ci_environment)
    assert "/reports/report%20%231.html" in capsys.readouterr().out


@pytest.mark.parametrize("job_type,strategy", [("presubmit", "single"), ("postsubmit", "single"), ("periodic", "legacy")])
def test_unsupported_upload_contract_is_local_only(ci_environment, job_type, strategy):
    spec = json.loads(ci_environment["JOB_SPEC"])
    spec["type"] = job_type
    spec["decoration_config"]["gcs_configuration"]["path_strategy"] = strategy
    ci_environment["JOB_SPEC"] = json.dumps(spec)
    assert artifact_urls(ci_environment["ARTIFACT_DIR"], ci_environment) is None


@pytest.mark.parametrize("check_exit", [0, 1])
@pytest.mark.parametrize("metadata_mode", ["local", "exported_hostname", "shell_hostname", "broken_helper"])
def test_orchestrator_preserves_results_and_exit_code(tmp_path, ci_environment, check_exit, metadata_mode):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy(ROOT / "scripts" / "gap-all.sh", scripts_dir)
    shutil.copytree(ROOT / "scripts" / "lib", scripts_dir / "lib")
    status = "FAIL" if check_exit else "PASS"
    (scripts_dir / "gap-aws-sts.py").write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "report_dir = Path(sys.argv[sys.argv.index('--report-dir') + 1])\n"
        f"data = {{'status': '{status}', 'details': {{'message': 'stub analysis result'}}}}\n"
        "(report_dir / 'status-check-1.json').write_text(json.dumps(data))\n"
        f"raise SystemExit({check_exit})\n"
    )
    (scripts_dir / "generate-combined-report.py").write_text("raise SystemExit(0)\n")
    report_dir = Path(ci_environment["ARTIFACT_DIR"]) / "rosa-gap-analysis-reports"
    report_dir.mkdir()
    (report_dir / "report.html").touch()
    environment = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    if metadata_mode in ("exported_hostname", "shell_hostname"):
        environment.update(ci_environment)
    command = ["bash", str(scripts_dir / "gap-all.sh")]
    if metadata_mode == "shell_hostname":
        del environment["HOSTNAME"]
        command = ["bash", "-c", 'HOSTNAME=nightly-5-0-5-0-gap-analysis; source "$@"', "bash", str(scripts_dir / "gap-all.sh")]
    if metadata_mode == "broken_helper":
        (scripts_dir / "lib" / "summary_artifacts.py").write_text("raise SystemExit(2)\n")
    result = subprocess.run(command + [
        "--baseline", "4.22.18", "--target", "5.0.0-rc.6",
        "--steps", "aws", "--report-dir", str(report_dir),
    ], env=environment, capture_output=True, text=True)
    assert result.returncode == check_exit, result.stderr
    expected_status = "FAILED" if check_exit else "SUCCESS"
    assert f"OVERALL STATUS: {expected_status}" in result.stdout
    assert f"CHECK #1-2: AWS STS Policy Gap - {status} (stub analysis result)" in result.stdout
    assert ("https://gcs.ci.openshift.org/" in result.stdout) == (metadata_mode in ("exported_hostname", "shell_hostname"))
    if metadata_mode == "broken_helper":
        assert "Unable to list artifact links" in result.stderr
