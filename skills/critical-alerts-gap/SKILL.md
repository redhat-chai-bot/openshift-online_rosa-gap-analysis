---
name: critical-alerts-gap
description: >
  Compare live ROSA PrometheusRule alerts between OpenShift versions using
  Critical Alerts snapshots. Recommends inherit vs silence vs
  review vs not-applicable. Informational; missing snapshots are SKIP.
compatibility:
  required_tools:
    - python3
    - curl (for Prow job-history and GCS artifact fetch)
---

# Critical Alerts Diff Validation

Compare PrometheusRule alerting rules on ROSA clusters using Critical Alerts
snapshots from Prow GCS. HCP, Classic, and OSD GCP, each compared to itself.
OSD GCP is skipped for OpenShift 5.x.

## When to Use

- Identifying new critical alerts in a target OpenShift version
- Deciding which new alerts SRE should inherit vs silence vs mark not-applicable
- Reviewing changed queries, `for` durations, or severity

## Script Usage

```bash
python3 ./scripts/gap-critical-alerts.py --version 4.22
python3 ./scripts/gap-critical-alerts.py --baseline 4.21 --target 4.22
python3 ./scripts/gap-critical-alerts.py --baseline 4.22 --target 5.0 --topology classic
./scripts/gap-all.sh --version 4.22 --steps critical-alerts
```

## Data Source

Prow GCS artifacts from HCP, Classic, and OSD GCP core jobs. CI step `as:` name:

- `rosa-gap-analysis-critical-alerts`

The step runs in the rosa-e2e **post** phase while the cluster is still up,
before deprovision. Files:

- `metadata.json`
- `alerts.json` (flattened alerting rules)

Recording rules are dropped.

HCP also writes the same files under `management/` from the Red Hat
management cluster (control plane). Hosted/guest files stay at the snapshot
root.

Jobs covered: daily HCP, Classic STS, and OSD GCP periodics.
OSD GCP is skipped for OpenShift 5.x (AWS/STS-only). Not HCP FIPS.
`--topology hcp` is HCP vs HCP (hosted + management when present).
`--topology classic` is Classic vs Classic. `--topology osd-gcp` is OSD GCP vs OSD GCP.
Prow channel: GA minors use the `staging-stable` job; pre-GA minors use
`staging-candidate` if that job has a snapshot, otherwise `staging-nightly`.

## Recommendations (v1 heuristics)

- **Inherit**: new critical, platform namespace (`openshift-*` / `kube-*`), runbook present
- **Silence**: new warning/info, or non-platform namespace
- **Review**: new critical missing inherit rules, or any expr/`for`/severity change
- **Not applicable**: rule groups that ship in the base OpenShift payload but can never fire on the target ROSA topology, scoped by (minor version, topology). Still counted in new_critical/new_other, but shown for awareness in a dedicated "Not applicable (non-ROSA topology)" section with its own summary row; no action needed. Example: TNF (Two-Node Fencing) `tnf-pacemaker.rules` on 5.0 classic — TNF is a bare-metal/edge topology (pacemaker + fencing/STONITH) and ROSA's cloud-managed control plane cannot be fenced.
- **Predicted frequency**: from `for` duration only (`<5m` high, `5m–1h` medium, `≥1h` low)

## Adding a not-applicable rule

To mark an alert group not-applicable for a specific version+topology, add ONE entry to the `NOT_APPLICABLE_ALERTS` dict in `scripts/gap-critical-alerts.py` — do NOT edit any function. Add an entry in the form `("<minor-version>", "<topology>"): ["<prometheus-rule-group>"]` (topology names: `classic`, `hcp`, `hcp-management`, `osd-gcp`); the value is a list of rule-group names. A key applies only to that exact pair (nothing is silenced globally); multiple groups per key are allowed. It is evaluated at runtime from the resolved target version + topology. Find the rule-group name in the Check #10 report (the alert card's "Rule group" field). The only active entry is `("5.0", "classic"): ["tnf-pacemaker.rules"]`.

## Exit Codes

- `0` - Success, including SKIP when snapshots are missing
- `1` - Execution failure
