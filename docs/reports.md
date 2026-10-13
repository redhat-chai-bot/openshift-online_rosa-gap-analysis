# Gap Analysis Reports

All gap analysis scripts automatically generate reports in multiple formats when executed.

## Summary Artifact Links

`scripts/gap-all.sh` always lists the local reports directory and HTML files.
For ci-operator periodic jobs using Prow's `single` GCS path strategy, it also
prints public URLs on `gcs.ci.openshift.org` when complete metadata is available:

- `JOB_SPEC` supplies the job, build ID, bucket, job type, and path strategy.
- `JOB_NAME` and `BUILD_ID`, when present, must agree with `JOB_SPEC`.
- `JOB_NAME_SAFE` supplies the multi-stage test target. Bash's `HOSTNAME`
  is the pod name `<target>-<step>`; removing the target prefix gives the
  step name. The script forwards it even when it is not exported.
- `ARTIFACT_DIR` identifies the uploaded directory. Reports must be inside it.

The [public periodic caller](https://github.com/openshift/release/blob/main/ci-operator/config/openshift-online/rosa-gap-analysis/openshift-online-rosa-gap-analysis-main__periodics.yaml)
sets `REPORT_DIR=${ARTIFACT_DIR}/rosa-gap-analysis-reports`.
[ci-operator pod generation](https://github.com/openshift/ci-tools/blob/90cf31998ee198bb268c2c708b93a6fca04d5f3c/pkg/steps/multi_stage/gen.go)
sets the target environment variable, pod name, and `<target>/<step>` upload directory.
The resulting report path is
`<bucket>/logs/<job>/<buildid>/artifacts/<target>/<step>/<artifact-directory-name>/<report-relative-path>/<filename>`.
For `nightly-5-0`, this includes
`artifacts/nightly-5-0/5-0-gap-analysis/artifacts/rosa-gap-analysis-reports/`.
The build log is at `<bucket>/logs/<job>/<buildid>/build-log.txt`.

Missing, malformed, unsupported, or ambiguous metadata produces local paths
only, never placeholder remote URLs. Truncated pod hostnames are not used.
If `BUILD_LOG` is set in a local run, its path is included in the summary.
Link generation does not affect analysis results or exit codes.

## Report Formats

Each script execution generates two report files:

1. **HTML (.html)** - Rich formatted report for viewing in browsers
2. **JSON (.json)** - Machine-readable data for automation

## Report Naming Convention

Reports are automatically named with timestamps:

```
gap-analysis-{type}_{baseline}_to_{target}_{timestamp}.{format}
```

**Examples:**
```
gap-analysis-aws-sts_4.20_to_4.21_20260325_153237.html
gap-analysis-aws-sts_4.20_to_4.21_20260325_153237.json

gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.html
gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.json

gap-analysis-full_4.20_to_4.21_20260325_153500.html
gap-analysis-full_4.20_to_4.21_20260325_153500.json
```

## Individual Script Reports

All reports follow the global 13-check validation system. See [Validation Checks](validation-checks.md) for details.

### AWS STS Gap Analysis (Checks 1-2)

```bash
python3 scripts/gap-aws-sts.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-aws-sts_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-aws-sts_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 1:** AWS STS Resources validation results
- **Check 2:** AWS STS Admin Ack validation results
- Added IAM actions/permissions
- Removed IAM actions/permissions
- **Changed Files**: Lists specific credential request files that changed with per-file diffs
- Total changes summary
- Validation results for [managed-cluster-config](https://github.com/openshift/managed-cluster-config)
- Timestamp and version information

### GCP WIF Gap Analysis (Checks 3-4)

```bash
python3 scripts/gap-gcp-wif.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-gcp-wif_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-gcp-wif_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 3:** GCP WIF Resources validation results
- **Check 4:** GCP WIF Admin Ack validation results
- Added GCP IAM permissions
- Removed GCP IAM permissions
- **Changed Files**: Lists specific credential request files that changed with per-file diffs
- Total changes summary
- Validation results for [managed-cluster-config](https://github.com/openshift/managed-cluster-config)
- Timestamp and version information

### OCP Admin Gate Acknowledgment Analysis (Check 5)

```bash
python3 scripts/gap-ocp-gate-ack.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-ocp-gate-ack_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-ocp-gate-ack_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 5:** OCP Admin Gates validation results
- Admin gates requiring acknowledgment
- Acknowledged gates
- Unacknowledged gates
- config.yaml validation results
- Timestamp and version information

### Versions & Channels Gap Analysis (Check 6)

```bash
python3 scripts/gap-versions-channels.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-versions-channels_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-versions-channels_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 6:** Versions & Channels validation results
- Channel availability across OCM channels (candidate/fast/stable/eus)
- Marketplace availability (ROSA Classic, ROSA HCP, OSD GCP)
- Timestamp and version information

### OCM Version Gate Gap Analysis (Check 7)

```bash
python3 scripts/gap-ocm-version-gate.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-ocm-version-gate_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-ocm-version-gate_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 7:** OCM Version Gates validation results
- Gate configurations for baseline and target versions
- New, common, and removed gates comparison
- Configuration metadata validation
- Timestamp and version information

### API Resources and CRD Gap Analysis (Check 9 - Informational)

```bash
python3 scripts/gap-api-resources.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-api-resources_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-api-resources_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 9:** API Resources and CRD Diff Validation from live cluster snapshots (informational)
- New / removed built-in API resources (HCP, Classic, and OSD GCP; OSD GCP skipped for 5.x)
- New / removed CRDs and their purpose
- API and CRD version changes (promotions, removed versions, storage version)
- Newly deprecated CRD versions that may affect managed services
- SKIP when API Resources and CRD snapshots are not yet in GCS

### Critical Alerts Diff Validation (Check 10 - Informational)

```bash
python3 scripts/gap-critical-alerts.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-critical-alerts_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-critical-alerts_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 10:** Critical Alerts Diff Validation from live PrometheusRule snapshots (informational)
- New critical alerts
- New alerts recommended to inherit vs silence
- Modified alerts (expr, for, severity) requiring review
- Predicted frequency heuristic from the rule `for` duration
- SKIP when Critical Alerts snapshots are not yet in GCS

### Cluster Install and Delete Validation (Check 11 - Informational)

```bash
python3 scripts/gap-cluster-install.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-cluster-install_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-cluster-install_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 11:** Cluster Install and Delete Validation from live ClusterOperator/node snapshots (informational)
- New / removed ClusterOperators
- Newly degraded or unavailable operators
- Node count and newly NotReady nodes
- Overall install status (PASSED/FAILED)
- SKIP when Cluster Install snapshots are not yet in GCS
- Note: the CI step captures install health before deprovision; delete-duration metrics are not in the snapshot yet

### Target E2E Validation and alert monitoring (Check 12 - Informational)

```bash
python3 scripts/gap-e2e-validation.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-e2e-validation_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-e2e-validation_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 12:** Target-version rosa-e2e JUnit (`junit-rosa-e2e.xml` from `as: rosa-e2e-test`) (informational)
- Per-topology PASS/FAIL/SKIP and failed test names (FAIL in the report does not fail the job)
- Alert monitoring subsection (SKIP until VerifyNoCriticalAlerts exists in rosa-e2e)
- OSD GCP skipped when the target is 5.x
- SKIP when JUnit is not yet in GCS

### Upgrade Validation from Y-1 to Y with E2E Tests (Check 13)

```bash
python3 scripts/gap-upgrade-e2e.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-upgrade-e2e_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-upgrade-e2e_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 13:** Y-1 → Y upgrade path from rosa-e2e HCP, Classic, and OSD GCP upgrade periodics
- Per-topology PASS/FAIL/SKIP, failed test names, and post-upgrade ClusterOperator health
- Upgrade duration from `upgrade-metrics.json` or `finished.json` timestamps
- Pre-upgrade COs and CO status changes when a before-snapshot is published; otherwise SKIP
- SKIP when upgrade JUnit is not yet in GCS, or no job matches the resolved target minor

### Feature Gate Gap Analysis (Check 8 - Informational)

```bash
python3 scripts/gap-feature-gates.py --baseline 4.20 --target 4.21
```

Generates:
- `gap-analysis-feature-gates_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-feature-gates_4.20_to_4.21_YYYYMMDD_HHMMSS.json`

**Report Contents:**
- **Check 8:** Feature Gates analysis (informational only, always PASS)
- New feature gates
- Removed feature gates
- Newly enabled by default
- Removed from default
- Total changes summary
- Timestamp and version information

## Combined Report (gap-all.sh) - All 13 Checks

When running the full gap analysis orchestrator:

```bash
bash scripts/gap-all.sh --baseline 4.20 --target 4.21
```

**Generates individual JSON reports for each analysis PLUS a combined report** (individual HTML is skipped when `GAP_FULL_REPORT=1`, which `gap-all.sh` sets by default):

- `gap-analysis-full_4.20_to_4.21_YYYYMMDD_HHMMSS.html`
- `gap-analysis-full_4.20_to_4.21_YYYYMMDD_HHMMSS.json`
- `status-check-<n>.json` — one per executed check (orchestrator summary)

**Combined Report Contents (All 13 Checks):**
- **Check 1:** AWS STS Resources validation
- **Check 2:** AWS STS Admin Ack validation
- **Check 3:** GCP WIF Resources validation
- **Check 4:** GCP WIF Admin Ack validation
- **Check 5:** OCP Admin Gates validation
- **Check 6:** Versions & Channels validation
- **Check 7:** OCM Version Gates validation
- **Check 8:** Feature Gates analysis (informational, always last)
- **Check 9:** API Resources and CRD Diff Validation (informational)
- **Check 10:** Critical Alerts Diff Validation (informational)
- **Check 11:** Cluster Install and Delete Validation (informational)
- **Check 12:** Target E2E Validation and alert monitoring (informational)
- **Check 13:** Upgrade Validation from Y-1 to Y with E2E Tests
- Aggregate statistics
- Timestamp and version information

**Execution Order:**
1. AWS STS (Checks 1-2)
2. GCP WIF (Checks 3-4)
3. OCP Admin Gates (Check 5)
4. Versions & Channels (Check 6)
5. OCM Version Gates (Check 7)
6. API Resources and CRD Diff Validation (Check 9)
7. Critical Alerts Diff Validation (Check 10)
8. Cluster Install and Delete Validation (Check 11)
9. Target E2E Validation and alert monitoring (Check 12)
10. Upgrade Validation from Y-1 to Y with E2E Tests (Check 13)
11. Feature Gates (Check 8) - Always executed last

## Report Verification

How reports, exit codes, and orchestrator status files relate to each other ([ROSAENG-60362](https://redhat.atlassian.net/browse/ROSAENG-60362)).

### Reporting layers

Each gap script produces up to four outputs:

| Layer | Location | Consumer |
|-------|----------|----------|
| Console | stderr via `log_*` helpers | Humans, Prow build log |
| JSON report | `reports/gap-analysis-<type>_*.json` | Combined report, CI parsers |
| HTML report | `reports/gap-analysis-<type>_*.html` (standalone mode) | Reviewers |
| Status file | `reports/status-check-<n>.json` | `gap-all.sh`, combined report fallbacks |

`gap-all.sh` sets `GAP_FULL_REPORT=1` by default so individual HTML is skipped; the combined report renders all sections. Run a script directly (without `gap-all.sh`) or unset `GAP_FULL_REPORT` to get standalone HTML.

### Exit code contract

| Script outcome | Process exit | `status-check` status | Job impact |
|----------------|-------------|------------------------|------------|
| Validation PASS | 0 | PASS | None |
| Validation FAIL (standard check) | 1 | FAIL | `gap-all.sh` exits 1 |
| Validation FAIL (informational check) | 0 | WARNING | Report shows FAIL; job continues |
| Missing data (SKIP) | 0 | SKIP | Informational only |
| Script crash / unhandled exception | 1 | FAIL (synthetic if missing) | `gap-all.sh` exits 1 |

**Standard checks** (can fail the job): #1–#7, #13  
**Informational checks** (report only): #8–#12

### Status file schema

Written by `scripts/lib/reporters.py`:

```json
{
  "check_number": 7,
  "check_name": "OCM Version Gates",
  "status": "FAIL",
  "exit_code": 1,
  "details": {
    "message": "1 validation failure(s): Deprecated gate in target: ...",
    "errors": ["Deprecated gate in target: ..."],
    "gates_count": 1
  }
}
```

- `message` — short summary for `gap-all.sh` console output
- `errors` — full validation errors (up to 20, with `errors_truncated` if more)
- Check-specific counters (`differences_count`, `gates_count`, etc.)

### Check → status file mapping

| Checks | Script | Status file |
|--------|--------|-------------|
| 1–2 | `gap-aws-sts.py` | `status-check-1.json` |
| 3–4 | `gap-gcp-wif.py` | `status-check-2.json` |
| 5 | `gap-ocp-gate-ack.py` | `status-check-3.json` |
| 6 | `gap-versions-channels.py` | `status-check-6.json` |
| 7 | `gap-ocm-version-gate.py` | `status-check-7.json` |
| 8 | `gap-feature-gates.py` | `status-check-8.json` |
| 9 | `gap-api-resources.py` | `status-check-9.json` |
| 10 | `gap-critical-alerts.py` | `status-check-10.json` |
| 11 | `gap-cluster-install.py` | `status-check-11.json` |
| 12 | `gap-e2e-validation.py` | `status-check-12.json` |
| 13 | `gap-upgrade-e2e.py` | `status-check-13.json` |

**Note:** Checks #1–#2 and #3–#4 share `status-check-1.json` and `status-check-2.json` respectively (one status file per script, not per global check number).

### Combined report fallbacks

`scripts/generate-combined-report.py` loads individual JSON reports. When a report file is missing (script crash), it builds a fallback section from `status-check-*.json` so failures are not silent in the combined HTML/JSON dashboard.

### Verification workflow

**Automated tests:**

```bash
make setup
make test
```

Covers status file schema, error collection helpers, and combined-report fallback logic.

**Manual pass-path check (single script):**

```bash
python3 scripts/gap-aws-sts.py --baseline 4.21.14 --target 4.21.15 --report-dir /tmp/gap-test
echo $?   # expect 0
jq . /tmp/gap-test/status-check-1.json
```

**Manual fail-path check (orchestrator):**

```bash
./scripts/gap-all.sh --baseline 4.21 --target 4.22 --steps aws
# If validation fails:
echo $?                            # expect 1
jq . reports/status-check-1.json   # status FAIL, errors populated
ls reports/gap-analysis-full_*.html
```

**Intentional failure scenarios:**

| Check | How to induce failure |
|-------|----------------------|
| AWS STS | Compare versions with known MCC drift (e.g. new CR in target) |
| GCP WIF | 4.x cross-minor with WIF permission drift |
| OCP gates | Target with unacknowledged admin gates |
| Versions/channels | GA target not in any channel |
| OCM version gate | Deprecated gates in live OCM data |
| Upgrade E2E | Failed post-upgrade JUnit in Prow artifacts |

Prefer fixture-based unit tests (`tests/`) over editing `managed-cluster-config` for CI.

### No silent failures checklist

- [ ] Script exit code matches validation result (standard checks)
- [ ] `status-check-*.json` exists after every script run
- [ ] JSON report contains `validation_details` / `errors` on FAIL
- [ ] HTML highlights FAIL sections (red styling, error lists)
- [ ] `gap-all.sh` summary lists failed check name and message
- [ ] Combined report includes failure details from all failed scripts
- [ ] Crash without JSON still produces synthetic FAIL via status file

## Viewing Reports

### HTML Reports (.html)

Open in any web browser:
```bash
firefox gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.html
```

Or:
```bash
open gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.html  # macOS
xdg-open gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.html  # Linux
```

**Features:**
- Professional styling with tables
- Color-coded changes (green for added, red for removed, orange for changed)
- Responsive design
- Print-friendly layout

### JSON Reports (.json)

Process programmatically:
```bash
jq '.' gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.json
```

Parse in scripts:
```python
import json
with open('gap-analysis-feature-gates_4.20_to_4.21_20260325_153237.json') as f:
    data = json.load(f)
    print(f"Total changes: {data['summary']['total_changes']}")
```

## Report Location

Reports are generated in `./reports/` by default.

To specify a different location:
```bash
python3 /path/to/scripts/gap-aws-sts.py --baseline 4.20 --target 4.21 --report-dir /path/to/reports
# Or via environment variable:
REPORT_DIR=/path/to/reports ./scripts/gap-all.sh --baseline 4.20 --target 4.21
```

## CI/CD Integration

### Archiving Reports

```yaml
# In ci-operator config
- as: gap-analysis-all
  commands: |
    gap-all.sh --baseline 4.20 --target 4.21
  container:
    from: src
  artifacts:
    - name: gap-analysis-reports
      path: gap-analysis-*.html
    - name: gap-analysis-reports
      path: gap-analysis-*.json
```

### Parsing JSON for Automation

```bash
#!/bin/bash
# Check if any differences were found
REPORT=$(ls -t gap-analysis-full_*.json | head -1)

AWS_CHANGES=$(jq '.aws_sts.summary.total_changes' "$REPORT")
GCP_CHANGES=$(jq '.gcp_wif.summary.total_changes' "$REPORT")
FG_CHANGES=$(jq '.feature_gates.summary.total_changes' "$REPORT")

if [ $AWS_CHANGES -gt 0 ] || [ $GCP_CHANGES -gt 0 ] || [ $FG_CHANGES -gt 0 ]; then
    echo "Changes detected - review required"
    # Send notification, create Jira ticket, etc.
fi
```

## Report Customization

The report generation is handled by `scripts/lib/reporters.py` using Jinja2 templates in `scripts/templates/`. To customize:

1. Edit HTML templates in `scripts/templates/*.html.j2`
2. Modify CSS styles within the HTML templates
3. Add new report formats (PDF, Excel, etc.) by extending `reporters.py`

See `scripts/lib/reporters.py` and `scripts/templates/` for implementation details.

## Troubleshooting

### Reports Not Generated

Check that the script completed successfully:
```bash
echo $?  # Should be 0
```

### Missing Reports

Verify you have write permissions in the current directory:
```bash
pwd
ls -la
```

### Large Reports

For versions with many changes, reports can be large. Use JSON for programmatic processing:
```bash
jq '.summary' gap-analysis-*.json  # Get summary only
```

## Future Enhancements

Planned features:
- PDF report generation
- Excel spreadsheet export
- Email notifications with attached reports
- Slack/Teams integration for posting reports
- Chart/graph generation for trends over time
