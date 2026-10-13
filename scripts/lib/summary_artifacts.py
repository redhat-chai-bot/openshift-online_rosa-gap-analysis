import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote


def artifact_urls(report_dir, environment):
    try:
        spec = json.loads(environment.get("JOB_SPEC", ""))
        gcs = spec["decoration_config"]["gcs_configuration"]
        job = spec["job"]
        build_id = spec["buildid"]
        bucket = gcs["bucket"]
        target = environment.get("JOB_NAME_SAFE", "")
        hostname = environment.get("HOSTNAME", "")
        artifact_dir = environment.get("ARTIFACT_DIR", "")
        if spec["type"] != "periodic" or gcs["path_strategy"] != "single":
            return None
        if not all(isinstance(value, str) and value for value in (job, build_id, bucket, target, hostname, artifact_dir)):
            return None
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", bucket) or not build_id.isdigit():
            return None
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", job):
            return None
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", target):
            return None
        if len(hostname) >= 63 or not hostname.startswith(f"{target}-"):
            return None
        step = hostname[len(target) + 1:]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", step):
            return None
        if environment.get("JOB_NAME", job) != job or environment.get("BUILD_ID", build_id) != build_id:
            return None
        relative_report_dir = Path(report_dir).resolve().relative_to(Path(artifact_dir).resolve())
    except (KeyError, TypeError, ValueError):
        return None

    job_path = f"{bucket}/logs/{job}/{build_id}"
    report_path = f"artifacts/{target}/{step}/{Path(artifact_dir).name}/{relative_report_dir.as_posix()}"
    return (
        f"https://gcs.ci.openshift.org/gcs/{job_path}/{quote(report_path, safe='/')}",
        f"https://gcs.ci.openshift.org/gcs/{job_path}/build-log.txt",
    )


def print_artifacts(report_dir, environment):
    urls = artifact_urls(report_dir, environment)
    print("ARTIFACTS:")
    print(f"- Reports directory: {report_dir.rstrip('/')}/")
    reports = sorted(report for report in Path(report_dir).glob("*.html") if report.is_file())
    if reports:
        print("- HTML reports:")
        for report in reports:
            location = f"{urls[0]}/{quote(report.name, safe='')}" if urls else str(report)
            print(f"  • {location}")
    if urls:
        print(f"- Build log: {urls[1]}")
    elif environment.get("BUILD_LOG"):
        print(f"- Build log: {environment['BUILD_LOG']}")


if __name__ == "__main__":
    print_artifacts(sys.argv[1], os.environ)
