# Validation Checks

The gap analysis framework performs 13 validation checks across all scripts.

## Check Numbering

All scripts use a consistent global check numbering system:

| Check # | Category | Description | Pass/Fail Impact |
|---------|----------|-------------|------------------|
| **1** | AWS STS Resources | Validates STS policy files exist in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `resources/sts/{version}/` and match OCP release changes (per-file comparison) | Exit code 1 on FAIL |
| **2** | AWS STS Admin Ack | Validates admin acknowledgment files in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `deploy/osd-cluster-acks/sts/{version}/` | Exit code 1 on FAIL |
| **3** | GCP WIF Resources | Validates WIF template (vanilla.yaml) in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `resources/wif/{version}/` and matches OCP release changes (per-file comparison) | Exit code 1 on FAIL |
| **4** | GCP WIF Admin Ack | Validates admin acknowledgment files in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `deploy/osd-cluster-acks/wif/{version}/` | Exit code 1 on FAIL |
| **5** | OCP Admin Gates | Validates admin gates from cluster-version-operator are acknowledged in [managed-cluster-config](https://github.com/openshift/managed-cluster-config) `deploy/osd-cluster-acks/ocp/{version}/` (conditional: if gates exist, both files required; if no gates, both files must be absent) | Exit code 1 on FAIL |
| **6** | Versions & Channels | Validates OCP version availability across OCM release channels (candidate/fast/stable/eus for GA, candidate-only for pre-GA) and marketplace availability (ROSA Classic via OCM API, ROSA HCP via ROSA CLI, OSD GCP via OCM API — 4.x only) | Exit code 1 on FAIL |
| **7** | OCM Version Gates | Validates OCM version gate existence, configurations, and metadata for target OCP versions compared to baseline version gates | Exit code 1 on FAIL |
| **8** | Feature Gates | Analyzes feature gate changes from Sippy API (Info only, always executed last). **Z-stream behavior:** When comparing z-stream versions (e.g., 4.21.15 → 4.21.16), shows default feature gates instead of differences | Always PASS (exit code 0) |
| **9** | API Resources and CRD Diff Validation | Compares live ROSA API resources and CRDs from HCP, Classic, and OSD GCP cluster snapshots. Each topology is compared to itself. OSD GCP is skipped for OpenShift 5.x (AWS/STS-only). Identifies new/removed APIs and CRDs, version promotions, and deprecations that may affect managed services. Missing snapshots are SKIP, not FAIL. | Always PASS (exit code 0) |
| **10** | Critical Alerts Diff Validation | Compares live PrometheusRule alerting rules from HCP, Classic, and OSD GCP cluster snapshots. Same topologies as Check #9. Identifies new critical alerts, modified queries/thresholds/severity, and recommends inherit vs silence vs review vs not-applicable. Missing snapshots are SKIP. | Always PASS (exit code 0) |
| **11** | Cluster Install and Delete Validation | Compares live ClusterOperator and node health from HCP, Classic, and OSD GCP cluster snapshots taken in the rosa-e2e **post** phase (before deprovision). Same topologies as Check #9. Identifies new/removed operators, newly degraded/unavailable operators, and NotReady nodes. Delete-duration metrics are not in the snapshot yet. Missing snapshots are SKIP. | Always PASS (exit code 0) |
| **12** | Target E2E Validation and alert monitoring | Consumes target-version `junit-rosa-e2e.xml` from the existing rosa-e2e test step. Does not compare baseline vs target. Fetches HCP, Classic, and OSD GCP JUnit. OSD GCP is skipped for OpenShift 5.x. Missing JUnit is SKIP. Failed e2e tests are reported as FAIL in the report and do not fail the job. Alert monitoring looks for a future VerifyNoCriticalAlerts test; until it exists the subsection is SKIP and does not fail the check. | Informational FAIL does not fail the job (exit 0); execution error exits 1 |
| **13** | Upgrade Validation from Y-1 to Y with E2E Tests | Consumes existing rosa-e2e Y-1 → Y upgrade periodics (HCP, Classic STS, and OSD GCP). Does not provision clusters. Missing upgrade JUnit is SKIP. Failed post-upgrade e2e tests FAIL. Post-upgrade degraded/unavailable ClusterOperators FAIL when a JSON or oc-get txt snapshot is present. Duration comes from `upgrade-metrics.json` or `finished.json` timestamps. Missing duration and pre-upgrade COs are subsection SKIP. | Exit code 1 on FAIL |


## Check Execution by Script

### gap-aws-sts.py
- **Check 1:** AWS STS Resources Validation
- **Check 2:** AWS STS Admin Acknowledgment

### gap-gcp-wif.py
- **Check 3:** GCP WIF Resources Validation
- **Check 4:** GCP WIF Admin Acknowledgment

### gap-ocp-gate-ack.py
- **Check 5:** OCP Admin Gate Acknowledgments

### gap-versions-channels.py
- **Check 6:** Versions & Channels Analysis

### gap-ocm-version-gate.py
- **Check 7:** OCM Version Gates Validation

### gap-feature-gates.py
- **Check 8:** Feature Gates Analysis (Info only, always last)

### gap-api-resources.py
- **Check 9:** API Resources and CRD Diff Validation (Info only; consumes live cluster snapshots)

### gap-critical-alerts.py
- **Check 10:** Critical Alerts Diff Validation (Info only; consumes live PrometheusRule snapshots)

### gap-cluster-install.py
- **Check 11:** Cluster Install and Delete Validation (Info only; consumes live ClusterOperator/node snapshots)

### gap-e2e-validation.py
- **Check 12:** Target E2E Validation and alert monitoring (Info only; consumes target-version junit-rosa-e2e.xml)

### gap-upgrade-e2e.py
- **Check 13:** Upgrade Validation from Y-1 to Y with E2E Tests (standard; consumes rosa-e2e Y-1 upgrade periodics)

### gap-all.sh (Combined)
Runs all checks in order:
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
11. Feature Gates (Check 8) - Info only, always executed last

### Standalone (not part of CI)
- **scripts/prod/gap-ga-validation.py** — GA Readiness Validation (run manually by SREs). See [ga-readiness-validation.md](ga-readiness-validation.md).

## Output Format

All checks follow a consistent output format:

### Success Output
```
============================================================
✓ VALIDATION PASSED - All checks successful
============================================================

CHECK #X: [Check Name] [PASS]
  Location: https://github.com/openshift/managed-cluster-config/tree/master/...
  ✓ Details about what was validated
  ✓ Additional success information
```

### Failure Output
```
============================================================
✗ VALIDATION FAILED
============================================================

CHECK #X: [Check Name] [FAIL]
Location: https://github.com/openshift/managed-cluster-config/tree/master/...

[Detailed error messages with GitHub URLs]
```

## Validation Results: Errors vs Warnings

The validation system distinguishes between **errors** (blocking issues) and **warnings** (informational):

| Result Type | Description | Impact |
|-------------|-------------|--------|
| **ERROR** | Mismatch between OCP release and managed-cluster-config (missing expected changes) | Validation FAILS (exit 1) |
| **WARNING** | Unexpected changes in managed-cluster-config (not in OCP release payload) | Validation PASSES but warns (exit 0) |

### Example Output

**ERROR (Validation Fails):**
```
MISMATCH: Expected actions added in OCP release but NOT found in managed-cluster-config:
  • ec2:DescribeVpcEndpoints
  • s3:CreateBucket
  Review policies at: https://github.com/openshift/managed-cluster-config/tree/master/resources/sts/4.22
```

**WARNING (Validation Passes with Information):**
```
UNEXPECTED: Actions added in managed-cluster-config (not in OCP release):
  • ec2:DescribeNetworkInterfaces
  Review policies at: https://github.com/openshift/managed-cluster-config/tree/master/resources/sts/4.22
  Files with unexpected changes:
    - sts_installer_permission_policy.json
      Introduced in PR #1234: https://github.com/openshift/managed-cluster-config/pull/1234
```

**PR Link Feature:** When unexpected changes are detected (warnings), the validation system automatically searches for the GitHub PR that introduced the change using the GitHub REST API (unauthenticated, 60 requests/hour). If a `GH_TOKEN` is available, it uses authenticated requests for higher rate limits and falls back to `gh` CLI if needed. This helps identify the context and reasoning behind managed-cluster-config changes that differ from the OCP payload.

## Validation Details

### Check 1: AWS STS Resources

**What it validates:**
- Target version directory exists: `resources/sts/{version}/`
- All policy files are valid JSON with required structure
- Policy changes match OCP release credential request changes using **per-file comparison**
- Per-file comparison aggregates all permission changes across individual CredentialRequest files (a permission can be new to one CR but already exist in another)
- New policy files (e.g. for a new CredentialsRequest) are reported as WARNINGS; removed policy files are ERRORS
- Actions (permissions) in managed-cluster-config match OCP release per-file changes

**Files checked:**
- All JSON files dynamically discovered in `resources/sts/{version}/`
- Typically 30+ policy files

**Pass criteria:**
- All policy files exist and are valid JSON
- Policy changes match OCP release changes exactly (ERRORS cause failure)
- Unexpected permissions and newly added policy files generate WARNINGS but do not fail validation
- Newly added policy file warnings include the MCC PR that introduced the file when resolvable
- Removed policy files fail validation

### Check 2: AWS STS Admin Ack

**What it validates:**
- `config.yaml` exists and is valid
- `config.yaml` has correct baseline version selector
- `osd-sts-ack_CloudCredential.yaml` exists and is valid
- CloudCredential has correct upgrade version annotation

**Files checked:**
- `deploy/osd-cluster-acks/sts/{version}/config.yaml`
- `deploy/osd-cluster-acks/sts/{version}/osd-sts-ack_CloudCredential.yaml`

**Pass criteria:**
- Both files exist and are valid YAML
- Baseline version matches expected (target - 1)
- Upgrade version matches target version

### Check 3: GCP WIF Resources

**What it validates:**
- Target version directory exists: `resources/wif/{version}/`
- `vanilla.yaml` exists and is valid
- WIF template has correct structure (id, kind, service_accounts)
- GCP permissions in template match OCP release changes using **per-file comparison**
- Per-file comparison aggregates all permission changes across individual CredentialRequest files (a permission can be new to one CR but already exist in another)

**Files checked:**
- `resources/wif/{version}/vanilla.yaml`

**Pass criteria:**
- vanilla.yaml exists and is valid YAML
- Template structure is correct
- GCP permissions match OCP release changes exactly (ERRORS cause failure)
- Unexpected permissions generate WARNINGS but do not fail validation

### Check 4: GCP WIF Admin Ack

**What it validates:**
- `config.yaml` exists and is valid
- `config.yaml` has correct baseline version selector
- `osd-wif-ack_CloudCredential.yaml` exists and is valid
- CloudCredential has correct upgrade version annotation

**Files checked:**
- `deploy/osd-cluster-acks/wif/{version}/config.yaml`
- `deploy/osd-cluster-acks/wif/{version}/osd-wif-ack_CloudCredential.yaml`

**Pass criteria:**
- Both files exist and are valid YAML
- Baseline version matches expected (target - 1)
- Upgrade version matches target version

### Check 5: OCP Admin Gates

**What it validates:**
- Admin gates from baseline version are acknowledged in target version
- Acknowledgment structure follows conditional presence rules
- All required gates are acknowledged when gates exist
- `config.yaml` and `admin-ack.yaml` are present together or absent together

**Z-stream vs Cross-minor Behavior:**
- **Z-stream upgrade** (e.g., 4.19.30 → 4.19.31): Gates from 4.19 are validated against acknowledgments in 4.20 (next minor)
  - Purpose: Detect if a z-stream adds a new gate that isn't acknowledged in the next minor version
  - Example: `OPENSHIFT_VERSION=4.19` validates gates in 4.19 against acks in 4.20
- **Cross-minor upgrade** (e.g., 4.19 → 4.20): Gates from 4.19 are validated against acknowledgments in 4.20
  - Standard validation: gates in version X must be acknowledged in version X+1

**Conditional validation logic:**
- **If gates exist in baseline**: BOTH `config.yaml` AND `admin-ack.yaml` MUST be present in target, all gates must be acknowledged
- **If no gates in baseline**: BOTH files MUST be absent (directory should not exist)
- Files must always be present together or absent together

**Files checked:**
- Admin gates from: `github.com/openshift/cluster-version-operator/release-{version}/...`
- Acknowledgments from: `deploy/osd-cluster-acks/ocp/{version}/admin-ack.yaml`
- Config from: `deploy/osd-cluster-acks/ocp/{version}/config.yaml`

**Pass criteria:**
- **No gates scenario**: Both `config.yaml` and `admin-ack.yaml` are absent
- **Gates exist scenario**: Both files present, all gates acknowledged, config.yaml has correct baseline version

**Orphaned Acknowledgment Files:**

When no admin gates exist in cluster-version-operator, acknowledgment files use a "both or neither" validation rule:

**Acknowledgment File Names:** Either `admin-ack.yaml` OR `admin-gates.yaml` is acceptable (script checks for both).

**Validation Rules (when no gates exist):**
- **Both files present** (acknowledgment file + config.yaml): **WARNING** with PR link (exit 0)
- **Only one file present**: **FAIL** - both files required together (exit 1)
- **Neither file present**: **PASS** - normal expected state (exit 0)

**Check order:** Acknowledgment file (admin-ack.yaml or admin-gates.yaml) is checked first, then config.yaml.

**Example Warning (both files present, no gates):**
```
⚠️ Warnings
- No admin gates found in cluster-version-operator for version 4.21, but unexpected admin-ack.yaml file is present in managed-cluster-config
  File: deploy/osd-cluster-acks/ocp/4.21/admin-ack.yaml
  Introduced in: https://github.com/openshift/managed-cluster-config/pull/2657
```

**PR Detection:** Uses commit history API to find the exact PR that added the admin-ack.yaml file, providing accurate attribution rather than title-based keyword matching.

### Check 6: Versions & Channels

**What it validates:**
- OCP version availability across OCM release channels (candidate/fast/stable/eus for GA versions, candidate-only for pre-GA)
- Marketplace availability: ROSA Classic (OCM API `rosa_enabled`), ROSA HCP (`rosa list versions --hosted-cp`), OSD GCP (OCM API `gcp_marketplace_enabled`, 4.x only — skipped for 5.x targets)

**Data sources:**
- OCM CLI: `ocm list versions` (channel availability, ROSA Classic/OSD GCP marketplace)
- ROSA CLI: `rosa list versions --hosted-cp` (ROSA HCP availability)
- Sippy API: GA version detection

**GA-aware channel checking:**
- GA versions are checked across all channels (candidate, fast, stable, eus)
- Pre-GA versions are checked in candidate channel only

**Marketplace severity (GA targets):**
- ROSA HCP missing → FAIL (all versions)
- ROSA Classic missing → FAIL (4.x) / WARN (5.x)
- OSD GCP missing → FAIL (4.x only, skipped for 5.x)
- Non-GA targets: all marketplace checks are informational only

**Pass criteria:**
- Channel availability FAIL: GA or next-after-GA target not found in any channel
- Marketplace FAIL: GA target missing from required marketplace (see severity above)
- Script exits 1 on validation FAIL or execution error

### Check 7: OCM Version Gates

**What it analyzes:**
- Checks if target minor version has corresponding version gate in OCM (via clusters-mgmt API `/api/clusters_mgmt/v1/version_gates`)
- Verifies enabled/disabled configurations and gate metadata (labels, descriptions, documentation links)
- Compares gate configurations between baseline (Y-1) and target (Y) to identify new or removed gates
- WIF gate excluded from comparison for 5.x+ targets (AWS/STS-only)

**Data source:**
- OCM API: `/api/clusters_mgmt/v1/version_gates` (via OCM CLI `ocm get`)

**Pass criteria:**
- FAIL: baseline gates missing from target (need to be created), or invalid gate metadata
- PASS: all baseline gate labels present in target with valid metadata
- Script exits 1 on validation FAIL or execution error
- Fallback gracefully to simulated/dry-run gates configuration if OCM credentials or CLI are absent

### Check 8: Feature Gates

**What it analyzes:**
- New feature gates added
- Feature gates removed
- Feature gates newly enabled by default
- Feature gates removed from default

**Data source:**
- Sippy API: `https://sippy.dptools.openshift.org/api/feature_gates?release={version}`

**Z-stream display behavior:**
- For z-stream comparisons (e.g., 4.21.15 → 4.21.16), the HTML report displays default feature gates in a collapsible drop-down list to improve readability
- The summary shows "📋 View all N Default:Hypershift gates (click to expand)"
- This helps distinguish informational gate listings from actual changes

**Pass criteria:**
- Always PASS (informational only)
- Analysis completes successfully
- Changes are tracked but do not affect exit code

### Check 9: API Resources and CRD Diff Validation

**What it analyzes:**
- New / removed built-in API resources
- New / removed CRDs and version promotions/deprecations
- Managed-service impact of CRD changes

**Data source:**
- Prow GCS snapshots from `rosa-gap-analysis-api-resources-and-crd` in the rosa-e2e **post** phase (`metadata.json`, `api-resources.json`, `crds.json`)
- Jobs: HCP, Classic STS, and OSD GCP periodics. OSD GCP is skipped for OpenShift 5.x (AWS/STS-only). Not HCP FIPS.
- HCP jobs also publish `management/` copies of those files from the Red Hat management cluster (control plane). Hosted/guest files stay at the snapshot root (customer data plane)
- Prow job channel: GA → `stable`; pre-GA → `candidate` if that job has a snapshot, else `nightly`

**Pass criteria:**
- Always PASS (informational only)
- Missing snapshots are SKIP, not FAIL
- Each topology is compared to itself (HCP, Classic, OSD GCP)
- OSD GCP is skipped for OpenShift 5.x (AWS/STS-only)

### Check 10: Critical Alerts Diff Validation

**What it analyzes:**
- New critical / other PrometheusRule alerts
- Inherit vs silence vs review vs not-applicable recommendations
- Modified expr / `for` / severity

**Data source:**
- Prow GCS snapshots from `rosa-gap-analysis-critical-alerts` in the rosa-e2e **post** phase (`metadata.json`, `alerts.json`)
- Jobs: HCP, Classic STS, and OSD GCP periodics. OSD GCP is skipped for OpenShift 5.x (AWS/STS-only). Not HCP FIPS.
- HCP jobs also publish `management/` copies of those files from the Red Hat management cluster (control plane)
- Prow job channel: GA → `stable`; pre-GA → `candidate` if that job has a snapshot, else `nightly`

**Pass criteria:**
- Always PASS (informational only)
- Missing snapshots are SKIP, not FAIL
- Each topology is compared to itself (HCP, Classic, OSD GCP)
- OSD GCP is skipped for OpenShift 5.x (AWS/STS-only)

**Not-applicable alerts:**

Some alert rule groups ship in the base OpenShift payload but can never fire on a given ROSA topology. They are not dropped — they still appear in the new critical/other counts, but their recommendation is `not-applicable` and they render in a dedicated "Not applicable (non-ROSA topology)" section with its own summary row (shown for awareness, no action needed). The determination is data-driven and scoped by `(minor version, topology)`, evaluated at runtime from the resolved target version + topology supplied by the Prow job.

Not-applicable groups are declared in the `NOT_APPLICABLE_ALERTS` dict in `gap-critical-alerts.py`:
- **Key:** `(minor version, topology)` — topology names are exactly `classic`, `hcp`, `hcp-management`, `osd-gcp` (from the snapshot metadata)
- **Value:** list of alert rule-group names (the PrometheusRule group) to mark not-applicable
- A key applies only to that exact `(version, topology)` pair; nothing is silenced globally. Multiple groups per key are allowed.

The only active entry marks TNF (Two-Node Fencing) `tnf-pacemaker.rules` not-applicable on 5.0 classic:

```python
NOT_APPLICABLE_ALERTS = {
    ("5.0", "classic"): ["tnf-pacemaker.rules"],
}
```

TNF is a bare-metal/edge topology (pacemaker + fencing/STONITH, two control-plane nodes); ROSA's control plane is cloud-managed and cannot be fenced, so TNF alerts can never fire on ROSA Classic.

**Adding a not-applicable rule:** add ONE entry to `NOT_APPLICABLE_ALERTS` — do NOT edit any function. Use the form `("<minor-version>", "<topology>"): ["<prometheus-rule-group>"]`. Find the rule-group name in the Check #10 report (the alert card's "Rule group" field, e.g. `tnf-pacemaker.rules`) — that is the string to add.

### Check 11: Cluster Install and Delete Validation

**What it analyzes:**
- ClusterOperator health (new/removed, newly degraded/unavailable, recovered)
- Node Ready status and node count
- Overall install status (PASSED/FAILED)

**Data source:**
- Prow GCS snapshots from `rosa-gap-analysis-cluster-install-delete-metrics` in the rosa-e2e **post** phase (`metadata.json`, `clusteroperators.json`, `nodes.json`)
- Jobs: HCP, Classic STS, and OSD GCP periodics. OSD GCP is skipped for OpenShift 5.x (AWS/STS-only). Not HCP FIPS.
- HCP jobs also publish `management/` copies of those files from the Red Hat management cluster (control plane). Hosted ClusterOperator/node health remains the FAIL/PASS source for the CI step itself
- Prow job channel: GA → `stable`; pre-GA → `candidate` if that job has a snapshot, else `nightly`
- The CI step captures install health while the cluster is still up, before deprovision. Delete-duration metrics are not in the snapshot yet.

**Pass criteria:**
- Always PASS (informational only)
- Missing snapshots are SKIP, not FAIL
- Each topology is compared to itself (HCP, Classic, OSD GCP)
- OSD GCP is skipped for OpenShift 5.x (AWS/STS-only)

### Check 12: Target E2E Validation and alert monitoring

**What it analyzes:**
- Target-version rosa-e2e JUnit results (pass/fail/skip)
- Alert monitoring subsection (future VerifyNoCriticalAlerts Ginkgo test)

**Data source:**
- Prow GCS `junit-rosa-e2e.xml` from `as: rosa-e2e-test` (`.../rosa-e2e-test/artifacts/junit-rosa-e2e.xml`)
- Prow job channel: GA → `stable`; pre-GA → `candidate` if that job has JUnit, else `nightly`
- Target version only — baseline JUnit is not fetched
- Does not use Check #10 `alerts.json` (those are PrometheusRule definitions, not firing state)

**Pass criteria:**
- Informational only — failed tests are reported as FAIL in the HTML/JSON report and do not fail the job (exit 0)
- SKIP when JUnit is missing
- Report FAIL when e2e tests fail, or the alert-monitoring test is present and failed
- Missing alert-monitoring test is SKIP for that subsection and does not fail the check
- OSD GCP is skipped for OpenShift 5.x (AWS/STS-only)

### Check 13: Upgrade Validation from Y-1 to Y with E2E Tests

**What it analyzes:**
- Post-upgrade rosa-e2e JUnit from Y-1 → Y upgrade periodics
- Post-upgrade ClusterOperator health from JSON snapshots or `oc get co -o wide` txt dumps
- Upgrade duration from `upgrade-metrics.json` or `finished.json` timestamps (operators-ready → upgrade step)
- Pre-upgrade ClusterOperator health and CO status changes when the upgrade step published a before-snapshot
- Heuristic grouping of failed tests (workloads, storage, network, managed operators)

**Data source:**
- Prow jobs:
  - `periodic-ci-openshift-online-rosa-e2e-main-upgrade-rosa-hcp-upgrade-staging-y-minus-1`
  - `periodic-ci-openshift-online-rosa-e2e-main-upgrade-rosa-classic-sts-upgrade-staging-y-minus-1`
  - `periodic-ci-openshift-online-rosa-e2e-main-upgrade-osd-gcp-upgrade-staging-y-minus-1`
- Post-upgrade `junit-rosa-e2e.xml` from `as: rosa-e2e-test`
- Post-upgrade Cluster Install snapshot (`clusteroperators.json` or `clusteroperators.txt`) from the same upgrade job
- `upgrade-metrics.json` when published; otherwise step `finished.json` timestamps
- Pre-upgrade `pre-upgrade-clusteroperators.json` from the upgrade step when published
- Does not provision or upgrade clusters; Check #12 remains target-version fresh-install JUnit

**Pass criteria:**
- PASS when parsed JUnit has no failing tests and post-upgrade COs (when present) are healthy
- SKIP when upgrade JUnit is missing, or no recent upgrade job matches the resolved target minor
- FAIL when e2e tests fail, a post-upgrade snapshot shows degraded/unavailable ClusterOperators, or a pre-upgrade snapshot shows the cluster was unhealthy before upgrade
- Missing duration and missing pre-upgrade COs are SKIP for those subsections and do not fail the check
- OSD GCP missing JUnit is SKIP until the y-minus-1 upgrade periodic has published artifacts
- OpenShift **5.x is AWS/STS-only**: use HCP/Classic for upgrades into 5.x. OSD GCP → 5.x is not a supported product path (expect SKIP / no matching job)
- Only consume a build whose post-upgrade ClusterOperator VERSION (or `cluster_version`) minor matches the resolved target

## Version Resolution

### OpenShift 5.x Major Version Mapping

Starting with OpenShift 5.0, the framework supports special version mappings to handle the major version transition from 4.x to 5.x:

**Upgrade Paths:**
- 4.19 → 4.20 → 4.21 → 4.22 → 4.23 (continues in 4.x line)
- 4.22 → 5.0 (first major bump to 5.x)
- 4.23 → 5.1 (second path to 5.x)
- 5.1 → 5.2 → 5.3 → ... (normal 5.x progression)

**Special Baseline Mappings:**

When using `--version` or `OPENSHIFT_VERSION` with 5.x versions, the framework automatically maps to the correct 4.x baseline:

| Target Version | Baseline Resolution | Example |
|---------------|---------------------|---------|
| `5.0` | 4.22.x (latest stable) | BASE=4.22.15, TARGET=5.0.0-rc.0 |
| `5.1` | 4.23.x (latest candidate) | BASE=4.23.0-rc.1, TARGET=5.1.0-rc.0 |
| `5.2+` | 5.(x-1) (normal progression) | BASE=5.1.5, TARGET=5.2.0-rc.0 |

**Usage Examples:**

**Python:**
```bash
# Compare 4.22 → 5.0 (first major bump)
python3 ./scripts/gap-aws-sts.py --version 5.0
# Resolves to: baseline=4.22.15, target=5.0.0-rc.0

# Compare 4.23 → 5.1 (second path to 5.x)
python3 ./scripts/gap-gcp-wif.py --version 5.1
# Resolves to: baseline=4.23.0-rc.1, target=5.1.0-rc.0

# Compare 5.1 → 5.2 (normal 5.x progression)
python3 ./scripts/gap-feature-gates.py --version 5.2
# Resolves to: baseline=5.1.5, target=5.2.0-rc.0
```

**Bash:**
```bash
# Using OPENSHIFT_VERSION environment variable
OPENSHIFT_VERSION=5.0 ./scripts/gap-all.sh
# Resolves to: BASE=4.22.15, TARGET=5.0.0-rc.0

OPENSHIFT_VERSION=5.1 ./scripts/gap-all.sh
# Resolves to: BASE=4.23.0-rc.1, TARGET=5.1.0-rc.0

# Using --version flag
./scripts/gap-all.sh --version 5.0  # Same as above
./scripts/gap-all.sh --version 5.1
```

**Why This Mapping Exists:**

The special mappings for 5.0 and 5.1 reflect the actual OpenShift upgrade paths during the major version transition:
- Clusters on 4.22 can upgrade to 5.0
- Clusters on 4.23 can upgrade to 5.1
- Starting with 5.2, upgrades follow normal sequential progression (5.1 → 5.2)

**Explicit Version Override:**

You can always override the automatic mapping by specifying both baseline and target explicitly:

```bash
# Override automatic mapping
./scripts/gap-all.sh --baseline 4.21 --target 5.0
python3 ./scripts/gap-aws-sts.py --baseline 4.23 --target 5.0
```

## Exit Codes

### Standard scripts (checks #1–#7, #13)

`gap-aws-sts.py`, `gap-gcp-wif.py`, `gap-ocp-gate-ack.py`, `gap-versions-channels.py`, `gap-ocm-version-gate.py`, `gap-upgrade-e2e.py`

- **Exit 0:** Validation PASS, SKIP (check #13 only), or dry-run
- **Exit 1:** Validation FAIL or execution error

### Informational scripts (checks #8–#12)

`gap-feature-gates.py`, `gap-api-resources.py`, `gap-critical-alerts.py`, `gap-cluster-install.py`, `gap-e2e-validation.py`

- **Exit 0:** Always on successful execution — including when the report records FAIL (check #12 uses `status-check` status `WARNING` so the orchestrator does not fail) or SKIP (missing Prow/JUnit artifacts)
- **Exit 1:** Execution error only (network, invalid version, unhandled exception)

### Combined script (`gap-all.sh`)

- **Exit 0:** Checks #1–#7 and #13 pass (or #13 SKIP); checks #8–#12 complete without execution errors; or dry-run
- **Exit 1:** Any standard check (#1–#7, #13) FAIL, or any executed script exits non-zero (including execution errors on informational checks)

See [reports.md](reports.md#exit-code-contract) for the `status-check-*.json` mapping.

## CI/CD Integration

The check numbering is consistent across:
- Console output
- Report files (HTML, JSON)
- Exit codes
- Log messages

This allows CI/CD systems to reliably:
- Parse specific check results from logs
- Identify which validation failed
- Link directly to [managed-cluster-config](https://github.com/openshift/managed-cluster-config) files needing updates
