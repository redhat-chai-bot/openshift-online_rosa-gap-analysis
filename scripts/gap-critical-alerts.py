#!/usr/bin/env python3
"""Critical Alerts Diff Validation - compare live ROSA PrometheusRule alerts."""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))

from common import log_error, log_info, log_success, log_warning
from openshift_releases import extract_minor_version, resolve_gap_versions
from prow_artifacts import (
    DEFAULT_TOPOLOGIES,
    TOPOLOGY_CHOICES,
    TOPOLOGY_HELP,
    find_critical_alerts_snapshot,
    iter_snapshot_role_results,
    load_critical_alerts_snapshot,
    osd_gcp_skip_reason,
    topology_coverage_summary,
    topology_display_name,
    topology_pair_label,
)
from reporters import generate_html_report, generate_json_report, generate_status_report

CHECK_NUMBER = 10
CHECK_NAME = "Critical Alerts Diff Validation"
REPORT_SLUG = "critical-alerts"
PLATFORM_NS_PREFIXES = ("openshift-", "kube-")
DURATION_RE = re.compile(r"(\d+)(ms|s|m|h|d)")

# Prometheus rule groups that target infrastructure managed OpenShift never runs,
# so their alerts can never fire on any managed cluster (ROSA HCP/Classic, OSD GCP)
# — on any version or topology. They ship in the base OCP payload but are
# intrinsically not applicable to managed platforms, so they are labelled
# "not-applicable" instead of inherit/silence/review. This mirrors how SREs
# manually drop non-actionable alerts during gap analysis: keyed on what the
# alert *is*, never on version or topology.
#
# To silence a new non-applicable group, add its ".rules" group name here.
#
# tnf-pacemaker.rules = TNF (Two-Node Fencing): bare-metal/edge topology
# (pacemaker + fencing/STONITH, two control-plane nodes). Managed OpenShift
# control planes are cloud-managed and cannot be fenced, so these never fire.
NON_MANAGED_PLATFORM_ALERT_GROUPS = frozenset({
    "tnf-pacemaker.rules",
})


def is_not_applicable_group(group):
    """True if this rule group targets infrastructure managed OpenShift never runs."""
    return (group or "") in NON_MANAGED_PLATFORM_ALERT_GROUPS


def parse_duration_seconds(value):
    """Parse a Prometheus duration string to seconds. Empty/missing is 0."""
    if not value:
        return 0
    total = 0
    for number, unit in DURATION_RE.findall(str(value).strip()):
        amount = int(number)
        if unit == "ms":
            total += amount / 1000.0
        elif unit == "s":
            total += amount
        elif unit == "m":
            total += amount * 60
        elif unit == "h":
            total += amount * 3600
        elif unit == "d":
            total += amount * 86400
    return int(total)


def predicted_frequency(for_duration):
    """Heuristic noise estimate from `for` only — not historical firing."""
    seconds = parse_duration_seconds(for_duration)
    if seconds < 300:
        return "high"
    if seconds < 3600:
        return "medium"
    return "low"


def is_platform_namespace(namespace):
    namespace = namespace or ""
    return any(namespace.startswith(prefix) for prefix in PLATFORM_NS_PREFIXES)


def critical_alert_index(snapshot):
    alerts = (snapshot.get("alerts.json") or {}).get("alerts") or []
    return {item.get("id"): item for item in alerts if item.get("id")}


def recommend_new_alert(alert):
    """Recommend not-applicable / inherit / silence / review for a new alert."""
    if is_not_applicable_group(alert.get("group")):
        return "not-applicable"
    severity = (alert.get("severity") or "").lower()
    runbook = ((alert.get("annotations") or {}).get("runbook_url") or "").strip()
    platform = is_platform_namespace(alert.get("namespace"))
    if severity == "critical" and platform and runbook:
        return "inherit"
    if severity == "critical":
        return "review"
    return "silence"


def critical_alert_card(alert, recommendation, extra=None):
    annotations = alert.get("annotations") or {}
    card = {
        "id": alert.get("id") or "",
        "alert": alert.get("alert") or "",
        "namespace": alert.get("namespace") or "",
        "prometheus_rule": alert.get("prometheus_rule") or "",
        "group": alert.get("group") or "",
        "severity": alert.get("severity") or "",
        "for": alert.get("for") or "",
        "expr": alert.get("expr") or "",
        "runbook_url": annotations.get("runbook_url") or "",
        "summary": annotations.get("summary") or "",
        "predicted_frequency": predicted_frequency(alert.get("for")),
        "recommendation": recommendation,
        "platform": is_platform_namespace(alert.get("namespace")),
    }
    if extra:
        card.update(extra)
    return card


def compare_critical_alerts(baseline, target):
    base = critical_alert_index(baseline)
    dest = critical_alert_index(target)
    base_ids = set(base)
    dest_ids = set(dest)

    new_critical = []
    new_other = []
    inherit = []
    silence = []
    review = []
    not_applicable = []

    for identity in sorted(dest_ids - base_ids):
        alert = dest[identity]
        recommendation = recommend_new_alert(alert)
        card = critical_alert_card(alert, recommendation)
        if (alert.get("severity") or "").lower() == "critical":
            new_critical.append(card)
        else:
            new_other.append(card)
        if recommendation == "not-applicable":
            not_applicable.append(card)
        elif recommendation == "inherit":
            inherit.append(card)
        elif recommendation == "silence":
            silence.append(card)
        else:
            review.append(card)

    removed = [critical_alert_card(base[identity], "") for identity in sorted(base_ids - dest_ids)]

    modified = []
    for identity in sorted(base_ids & dest_ids):
        before = base[identity]
        after = dest[identity]
        changes = []
        if (before.get("expr") or "") != (after.get("expr") or ""):
            changes.append("expr")
        if (before.get("for") or "") != (after.get("for") or ""):
            changes.append("for")
        if (before.get("severity") or "").lower() != (after.get("severity") or "").lower():
            changes.append("severity")
        if (before.get("labels") or {}) != (after.get("labels") or {}):
            changes.append("labels")
        before_ann = before.get("annotations") or {}
        after_ann = after.get("annotations") or {}
        if before_ann != after_ann:
            changes.append("annotations")
        if not changes:
            continue
        card = critical_alert_card(
            after,
            "review",
            extra={
                "changed_fields": changes,
                "baseline_severity": before.get("severity") or "",
                "baseline_for": before.get("for") or "",
                "baseline_expr": before.get("expr") or "",
            },
        )
        modified.append(card)
        review.append(card)

    return {
        "new_critical": new_critical,
        "new_other": new_other,
        "removed": removed,
        "modified": modified,
        "inherit": inherit,
        "silence": silence,
        "review": review,
        "not_applicable": not_applicable,
    }


def summarize_critical_alerts(comparison):
    return {
        "new_critical": len(comparison["new_critical"]),
        "new_other": len(comparison["new_other"]),
        "removed": len(comparison["removed"]),
        "modified": len(comparison["modified"]),
        "inherit": len(comparison["inherit"]),
        "silence": len(comparison["silence"]),
        "review": len(comparison["review"]),
        "not_applicable": len(comparison["not_applicable"]),
    }


def total_changes(summary):
    return (
        summary.get("new_critical", 0)
        + summary.get("new_other", 0)
        + summary.get("removed", 0)
        + summary.get("modified", 0)
    )


def critical_alerts_source(snapshot):
    source = snapshot.get("source") or {}
    meta = snapshot.get("metadata.json") or {}
    return {
        "job_name": source.get("job_name"),
        "build_id": source.get("build_id"),
        "gcs_url": source.get("gcs_url"),
        "cluster_version": meta.get("cluster_version") or "",
        "openshift_version": meta.get("openshift_version") or "",
        "captured_at": meta.get("captured_at") or "",
        "cluster_id": meta.get("cluster_id") or "",
        "topology": meta.get("topology") or "",
        "cluster_role": meta.get("cluster_role") or source.get("cluster_role") or "",
        "alert_count": meta.get("alert_count"),
        "critical_count": meta.get("critical_count"),
        "prometheus_rule_count": meta.get("prometheus_rule_count"),
    }


def empty_critical_alerts_comparison():
    return {
        "new_critical": [],
        "new_other": [],
        "removed": [],
        "modified": [],
        "inherit": [],
        "silence": [],
        "review": [],
        "not_applicable": [],
    }


def compare_critical_alerts_topology(
    topology, baseline_snapshot, target_snapshot,
    baseline_topology=None, target_topology=None,
):
    baseline_topology = baseline_topology or topology
    target_topology = target_topology or topology
    comparison = compare_critical_alerts(baseline_snapshot, target_snapshot)
    label = topology_pair_label(baseline_topology, target_topology)
    return {
        "topology": label,
        "display_name": topology_display_name(label),
        "baseline_topology": baseline_topology,
        "target_topology": target_topology,
        "status": "PASS",
        "skip_reason": "",
        "baseline": critical_alerts_source(baseline_snapshot),
        "target": critical_alerts_source(target_snapshot),
        "comparison": comparison,
        "summary": summarize_critical_alerts(comparison),
    }


def skip_critical_alerts_topology(
    topology, reason, baseline_topology=None, target_topology=None,
):
    log_warning(f"{topology}: {reason}")
    comparison = empty_critical_alerts_comparison()
    baseline_topology = baseline_topology or topology
    target_topology = target_topology or topology
    label = topology_pair_label(baseline_topology, target_topology)
    return {
        "topology": label,
        "display_name": topology_display_name(label),
        "baseline_topology": baseline_topology,
        "target_topology": target_topology,
        "status": "SKIP",
        "skip_reason": reason,
        "baseline": {},
        "target": {},
        "comparison": comparison,
        "summary": summarize_critical_alerts(comparison),
    }


def print_critical_alerts_topology(result, verbose=False):
    topology = result.get("display_name") or result["topology"]
    if result["status"] == "SKIP":
        log_warning(f"  {topology}: SKIP ({result['skip_reason']})")
        return

    summary = result["summary"]
    log_info(
        f"  {topology}: +{summary['new_critical']} critical, "
        f"+{summary['new_other']} other, -{summary['removed']} removed, "
        f"{summary['modified']} modified | inherit={summary['inherit']} "
        f"silence={summary['silence']} review={summary['review']} "
        f"not-applicable={summary['not_applicable']}"
    )
    if verbose:
        for item in result["comparison"]["inherit"]:
            log_info(f"    inherit {item['alert']} ({item['namespace']}) freq={item['predicted_frequency']}")
        for item in result["comparison"]["silence"]:
            log_info(f"    silence {item['alert']} ({item['namespace']}) severity={item['severity']}")
        for item in result["comparison"]["not_applicable"]:
            log_info(f"    not-applicable {item['alert']} ({item['group']})")
        for item in result["comparison"]["modified"]:
            log_info(
                f"    review {item['alert']} changed={','.join(item.get('changed_fields') or [])}"
            )


def main():
    parser = argparse.ArgumentParser(
        description="Compare live ROSA PrometheusRule alerts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --version 4.22
  %(prog)s --baseline 4.21 --target 4.22
  %(prog)s --baseline 4.22 --target 5.0
  %(prog)s --version 5.0
  %(prog)s --baseline 4.22 --target 5.0 --topology classic
  %(prog)s --baseline-dir /tmp/base --target-dir /tmp/target --topology hcp

Exit Codes:
  0 - Successful execution (informational; missing snapshots are SKIP)
  1 - Execution failure
        """,
    )
    parser.add_argument("--version", help="Single version to analyze (auto-resolves baseline and target)")
    parser.add_argument("--baseline", help="Baseline version (requires --target)")
    parser.add_argument("--target", help="Target version (requires --baseline)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--report-dir", default=os.environ.get("REPORT_DIR", "reports"),
                        help="Directory to store reports")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show versions that would be used and exit")
    parser.add_argument("--topology", action="append", dest="topologies",
                        choices=list(TOPOLOGY_CHOICES),
                        help=TOPOLOGY_HELP)
    parser.add_argument("--baseline-dir", help="Local baseline snapshot directory (skips GCS)")
    parser.add_argument("--target-dir", help="Local target snapshot directory (skips GCS)")
    args = parser.parse_args()

    if bool(args.baseline_dir) != bool(args.target_dir):
        log_error("--baseline-dir and --target-dir must be used together")
        sys.exit(1)

    baseline_full, target_full = resolve_gap_versions(
        version=args.version, baseline=args.baseline, target=args.target
    )
    baseline_minor = extract_minor_version(baseline_full)
    target_minor = extract_minor_version(target_full)
    topologies = tuple(args.topologies) if args.topologies else DEFAULT_TOPOLOGIES

    start_time = datetime.now()
    log_info("Starting Critical Alerts Diff Validation")
    log_info("=========================================")
    log_info(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    log_info(f"Baseline version: {baseline_full} (minor: {baseline_minor})")
    log_info(f"Target version: {target_full} (minor: {target_minor})")
    log_info(f"Topologies: {', '.join(topologies)}")
    for topology in topologies:
        log_info(f"  {topology}: {topology} {baseline_minor} → {topology} {target_minor}")
    log_info("=========================================")

    if args.dry_run:
        log_info("Dry-run mode enabled - exiting without performing analysis")
        sys.exit(0)

    topology_results = []
    gcp_skip = osd_gcp_skip_reason(baseline_minor, target_minor)
    if args.baseline_dir and args.target_dir:
        if len(topologies) != 1:
            log_error("Local snapshot dirs require exactly one --topology")
            sys.exit(1)
        topology = topologies[0]
        if topology == "osd-gcp" and gcp_skip:
            topology_results.append(skip_critical_alerts_topology(
                topology, gcp_skip,
            ))
        else:
            try:
                baseline_snapshot = load_critical_alerts_snapshot(args.baseline_dir)
                target_snapshot = load_critical_alerts_snapshot(args.target_dir)
                for label, bsnap, tsnap, skip_reason in iter_snapshot_role_results(
                    topology, baseline_snapshot, target_snapshot, "Critical Alerts",
                ):
                    if skip_reason:
                        topology_results.append(skip_critical_alerts_topology(
                            label, skip_reason,
                        ))
                        continue
                    topology_results.append(
                        compare_critical_alerts_topology(
                            label, bsnap, tsnap,
                        )
                    )
            except (OSError, ValueError, json.JSONDecodeError) as err:
                topology_results.append(skip_critical_alerts_topology(
                    topology, str(err),
                ))
    else:
        for topology in topologies:
            if topology == "osd-gcp" and gcp_skip:
                topology_results.append(skip_critical_alerts_topology(
                    topology, gcp_skip,
                ))
                continue
            baseline_snapshot = find_critical_alerts_snapshot(baseline_minor, topology)
            target_snapshot = find_critical_alerts_snapshot(target_minor, topology)
            for label, bsnap, tsnap, skip_reason in iter_snapshot_role_results(
                topology, baseline_snapshot, target_snapshot, "Critical Alerts",
                baseline_minor=baseline_minor, target_minor=target_minor,
            ):
                if skip_reason:
                    topology_results.append(skip_critical_alerts_topology(
                        label, skip_reason,
                    ))
                    continue
                topology_results.append(
                    compare_critical_alerts_topology(
                        label, bsnap, tsnap,
                    )
                )

    compared = [result for result in topology_results if result["status"] != "SKIP"]
    skipped = [result for result in topology_results if result["status"] == "SKIP"]
    coverage = topology_coverage_summary(topology_results)

    combined_summary = {
        "new_critical": 0,
        "new_other": 0,
        "removed": 0,
        "modified": 0,
        "inherit": 0,
        "silence": 0,
        "review": 0,
        "not_applicable": 0,
        **coverage,
    }
    for result in compared:
        for key in ("new_critical", "new_other", "removed", "modified", "inherit", "silence", "review", "not_applicable"):
            combined_summary[key] += result["summary"].get(key, 0)

    if not compared:
        validation_result = "SKIP"
        status_message = "; ".join(result["skip_reason"] for result in skipped) or "no snapshots found"
    else:
        validation_result = "PASS"
        changes = total_changes(combined_summary)
        if changes == 0:
            status_message = f"no alert changes ({', '.join(combined_summary['compared_display_names'])})"
        else:
            status_message = (
                f"{changes} change(s) across {', '.join(combined_summary['compared_display_names'])}; "
                f"inherit={combined_summary['inherit']} silence={combined_summary['silence']} "
                f"review={combined_summary['review']}"
            )

    log_info(f"\nCHECK #{CHECK_NUMBER}: {CHECK_NAME}")
    for result in topology_results:
        print_critical_alerts_topology(result, verbose=args.verbose)

    report_dir = args.report_dir
    os.makedirs(report_dir, exist_ok=True)
    timestamp_suffix = f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    report_data = {
        "type": CHECK_NAME,
        "baseline": baseline_full,
        "target": target_full,
        "baseline_minor": baseline_minor,
        "target_minor": target_minor,
        "timestamp": datetime.now().isoformat(),
        "validation_result": validation_result,
        "topologies": topology_results,
        "summary": combined_summary,
        "error_message": status_message,
        "note": (
            "Informational check. Snapshots come from live HCP, Classic, and OSD GCP "
            "PrometheusRule alerts. Each topology is compared to itself. HCP also compares "
            "management-cluster alerts (control plane) when ARTIFACT_DIR/management/ is present. "
            "OSD GCP is skipped for OpenShift 5.x (AWS/STS-only). "
            "Inherit/silence/review recommendations are heuristics from severity, namespace, and runbook; "
            "not-applicable marks rule groups that can never fire on the target ROSA topology "
            "(scoped by version and topology). "
            "Predicted frequency is inferred from the rule's `for` duration, not historical firing."
        ),
    }

    json_file = os.path.join(
        report_dir,
        f"gap-analysis-{REPORT_SLUG}_{baseline_minor}_to_{target_minor}{timestamp_suffix}.json",
    )
    generate_json_report(report_data, json_file)
    log_info(f"JSON report generated: {json_file}")

    # Skip HTML when GAP_FULL_REPORT is set (combined report includes this check)
    if os.environ.get("GAP_FULL_REPORT"):
        log_info("Skipping HTML reports (full report will be generated)")
    else:
        html_file = os.path.join(
            report_dir,
            f"gap-analysis-{REPORT_SLUG}_{baseline_minor}_to_{target_minor}{timestamp_suffix}.html",
        )
        generate_html_report(report_data, html_file)
        log_info(f"HTML report generated: {html_file}")

    log_success("=" * 60)
    if validation_result == "SKIP":
        log_warning(f"CHECK #{CHECK_NUMBER}: {CHECK_NAME} [SKIP]")
        log_warning(f"  {status_message}")
        log_warning("  Snapshots come from live HCP, Classic, and OSD GCP PrometheusRule alerts.")
    else:
        log_success(f"✓ VALIDATION PASSED - {CHECK_NAME} (Informational)")
        log_success("=" * 60)
        log_success(f"CHECK #{CHECK_NUMBER}: {CHECK_NAME} [PASS - Info]")
        log_success(f"  {status_message}")
        if combined_summary["new_critical"]:
            log_success(f"    • {combined_summary['new_critical']} new critical alert(s)")
        if combined_summary["inherit"]:
            log_success(f"    • {combined_summary['inherit']} recommended inherit")
        if combined_summary["silence"]:
            log_warning(f"    • {combined_summary['silence']} recommended silence")
        if combined_summary["review"]:
            log_warning(f"    • {combined_summary['review']} requiring review")
        if skipped:
            log_warning(f"  Skipped topologies: {', '.join(r.get('display_name') or r['topology'] for r in skipped)}")
        log_success(f"✅ PASSED - {CHECK_NAME} analysis complete (informational)")

    generate_status_report(
        check_number=CHECK_NUMBER,
        check_name=CHECK_NAME,
        status=validation_result,
        details={
            "message": status_message,
            "differences_count": total_changes(combined_summary),
            "compared_topologies": combined_summary["compared_topologies"],
            "skipped_topologies": combined_summary["skipped_topologies"],
        },
        report_dir=args.report_dir,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
