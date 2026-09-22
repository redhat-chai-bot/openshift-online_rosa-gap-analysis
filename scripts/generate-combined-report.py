#!/usr/bin/env python3
"""Generate combined report from individual gap analysis JSON reports."""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))

from reporters import generate_html_report, generate_json_report
from common import log_info, log_success
from openshift_releases import extract_minor_version, get_next_minor_version


def parse_build_log(log_path):
    """Parse build log for metrics, status, infrastructure/build failures, and tracebacks."""
    metrics = {
        'duration': 'Unknown',
        'errors_count': 0,
        'warnings_count': 0,
        'status': 'SUCCESS',
        'failures': [],
        'retries': []
    }

    if not log_path or not os.path.exists(log_path):
        return metrics

   # Determine build log URL
    job = os.environ.get('job') or os.environ.get('JOB_NAME')
    buildid = os.environ.get('buildid') or os.environ.get('BUILD_ID')
    if job and buildid:
        metrics['build_log_url'] = f"https://prow.ci.openshift.org/view/gs/test-platform-results/logs/{job}/{buildid}/build-log.txt"
    else:
        metrics['build_log_url'] = f"file://{os.path.abspath(log_path)}"

    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Clean ANSI escape sequences
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean_content = ansi_escape.sub('', content)
        lines = clean_content.splitlines()

        # 1. Parse duration
        duration_match = re.search(r'Ran for\s+(\w+)', clean_content)
        if duration_match:
            metrics['duration'] = duration_match.group(1)
        else:
            pod_match = re.search(r'failed after\s+(\w+)', clean_content)
            if pod_match:
                metrics['duration'] = pod_match.group(1)

        # 2. Count errors and warnings
        error_lines = [line for line in lines if any(x in line.upper() for x in ['ERROR', 'ERRO[', '❌ FAILED', 'CONTAINERFAILED'])]
        warning_lines = [line for line in lines if any(x in line.upper() for x in ['WARN', '⚠'])]

        metrics['errors_count'] = len(error_lines)
        metrics['warnings_count'] = len(warning_lines)

        # 3. Overall status
        if any(x in clean_content.upper() for x in ['❌ FAILED', 'SOME STEPS FAILED', 'CONTAINERFAILED']):
            metrics['status'] = 'FAILED'

        # 4. Extract infrastructure/build failures
        build_fail_matches = re.findall(r'Build\s+(\S+)\s+failed', clean_content)
        for component in set(build_fail_matches):
            metrics['failures'].append({
                'type': 'Build Failure',
                'component': component,
                'detail': f"Build of image '{component}' failed during the run.",
                'log_url': metrics.get('build_log_url')
            })

        # 5. Extract retry events
        retry_matches = re.findall(r'(\S+)\s+previously failed.*retrying', clean_content)
        for component in set(retry_matches):
            metrics['retries'].append({
                'component': component,
                'detail': f"Build previously failed, retrying component."
            })

        # 6. Extract test script traceback if any
        if 'Traceback (most recent call last):' in clean_content:
            tb_index = clean_content.find('Traceback (most recent call last):')
            tb_part = clean_content[tb_index:]
            tb_lines = tb_part.splitlines()[:15]
            traceback_text = '\n'.join(tb_lines)
            metrics['failures'].append({
                'type': 'Script Exception',
                'component': 'Test Validation Step',
                'detail': traceback_text,
                'log_url': metrics.get('build_log_url')
            })

        # 7. Extract specific failed pod details
        pod_fail_match = re.search(r'pod\s+(\S+)\s+failed after\s+(\S+)\s+\(([^)]+)\)', clean_content)
        if pod_fail_match:
            metrics['failures'].append({
                'type': 'Pod Failure',
                'component': pod_fail_match.group(1),
                'detail': f"Pod failed after {pod_fail_match.group(2)}. Failed containers: {pod_fail_match.group(3)}",
                'log_url': metrics.get('build_log_url')
            })

        # 8. Extract error log lines into failures
        if error_lines:
            # Take up to 20 lines of errors to avoid bloating the report
            error_summary = "\n".join(error_lines[:20])
            if len(error_lines) > 20:
                error_summary += f"\n... and {len(error_lines) - 20} more error lines."

            metrics['failures'].append({
                'type': 'Log Errors Detected',
                'component': 'Build Log',
                'detail': error_summary,
                'log_url': metrics.get('build_log_url')
            })

    except Exception as e:
        log_info(f"Error parsing build log: {e}")
        metrics['status'] = 'FAILED'
        metrics['failures'].append({
            'type': 'Build Log Parsing Error',
            'component': 'Build Log Parser',
            'detail': f"An error occurred while parsing the build log at {log_path}: {str(e)}",
            'log_url': metrics.get('build_log_url')
        })

    return metrics


def load_status_check_file(report_dir, check_num):
    """Load orchestrator status-check JSON for a check number."""
    status_file = os.path.join(report_dir, f"status-check-{check_num}.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return None


def get_status_message(report_dir, check_num, default_msg):
    """Return details.message from a status-check file, or default."""
    status_data = load_status_check_file(report_dir, check_num)
    if status_data:
        return status_data.get('details', {}).get('message', default_msg)
    return default_msg


def fallback_validation_result(report_dir, check_num, default='SKIP'):
    """Preserve FAIL from a crashed check; SKIP only when the check did not run."""
    status_data = load_status_check_file(report_dir, check_num)
    if not status_data:
        return default
    status = status_data.get('status') or default
    if status in ('FAIL', 'ERROR'):
        return 'FAIL'
    if status in ('PASS', 'SKIP', 'WARNING', 'WARN'):
        return status if status != 'WARN' else 'WARNING'
    return default


def find_latest_reports(baseline, target, report_dir='reports'):
    """Find the latest JSON reports for each analysis type."""
    reports = {
        'aws_sts': None,
        'gcp_wif': None,
        'feature_gates': None,
        'ocp_gate_ack': None,
        'ocm_version_gate': None,
        'versions_channels': None,
        'api_resources': None,
        'critical_alerts': None,
        'cluster_install': None,
        'e2e_validation': None,
        'upgrade_e2e': None,
    }

    # Find AWS STS report
    aws_pattern = os.path.join(report_dir, f"gap-analysis-aws-sts_{baseline}_to_{target}_*.json")
    aws_files = sorted(glob.glob(aws_pattern))
    if aws_files:
        reports['aws_sts'] = aws_files[-1]  # Latest

    # Find GCP WIF report
    gcp_pattern = os.path.join(report_dir, f"gap-analysis-gcp-wif_{baseline}_to_{target}_*.json")
    gcp_files = sorted(glob.glob(gcp_pattern))
    if gcp_files:
        reports['gcp_wif'] = gcp_files[-1]  # Latest

    # Find Feature Gates report (uses minor versions)
    baseline_minor = extract_minor_version(baseline)
    target_minor = extract_minor_version(target)
    fg_pattern = os.path.join(report_dir, f"gap-analysis-feature-gates_{baseline_minor}_to_{target_minor}_*.json")
    fg_files = sorted(glob.glob(fg_pattern))
    if fg_files:
        reports['feature_gates'] = fg_files[-1]  # Latest

    # Find OCP Gate Acknowledgment report (uses minor versions)
    # For z-stream upgrades, OCP gate ack uses next minor version for ack_check_version
    # Try both patterns and pick the latest by timestamp
    oga_files = []

    # Pattern 1: standard (baseline_to_target)
    oga_pattern1 = os.path.join(report_dir, f"gap-analysis-ocp-gate-ack_{baseline_minor}_to_{target_minor}_*.json")
    oga_files.extend(glob.glob(oga_pattern1))

    # Pattern 2: z-stream (baseline_to_next) - only for z-stream upgrades
    if baseline_minor == target_minor:
        next_minor = get_next_minor_version(baseline_minor)
        oga_pattern2 = os.path.join(report_dir, f"gap-analysis-ocp-gate-ack_{baseline_minor}_to_{next_minor}_*.json")
        oga_files.extend(glob.glob(oga_pattern2))

    # Sort all found files and pick the latest
    if oga_files:
        reports['ocp_gate_ack'] = sorted(oga_files)[-1]  # Latest by filename (timestamp)

    # Find OCM Version Gate report (uses minor versions)
    ovg_pattern = os.path.join(report_dir, f"gap-analysis-ocm-version-gate_{baseline_minor}_to_{target_minor}_*.json")
    ovg_files = sorted(glob.glob(ovg_pattern))
    if ovg_files:
        reports['ocm_version_gate'] = ovg_files[-1]  # Latest

    # Find Versions & Channels report (uses minor versions)
    vc_pattern = os.path.join(report_dir, f"gap-analysis-versions-channels_{baseline_minor}_to_{target_minor}_*.json")
    vc_files = sorted(glob.glob(vc_pattern))
    if vc_files:
        reports['versions_channels'] = vc_files[-1]  # Latest

    # Find API Resources and CRD report (uses minor versions)
    ar_pattern = os.path.join(report_dir, f"gap-analysis-api-resources_{baseline_minor}_to_{target_minor}_*.json")
    ar_files = sorted(glob.glob(ar_pattern))
    if ar_files:
        reports['api_resources'] = ar_files[-1]

    # Find Critical Alerts report (uses minor versions)
    ca_pattern = os.path.join(report_dir, f"gap-analysis-critical-alerts_{baseline_minor}_to_{target_minor}_*.json")
    ca_files = sorted(glob.glob(ca_pattern))
    if ca_files:
        reports['critical_alerts'] = ca_files[-1]

    # Find Cluster Install report (uses minor versions)
    ci_pattern = os.path.join(report_dir, f"gap-analysis-cluster-install_{baseline_minor}_to_{target_minor}_*.json")
    ci_files = sorted(glob.glob(ci_pattern))
    if ci_files:
        reports['cluster_install'] = ci_files[-1]

    ev_pattern = os.path.join(report_dir, f"gap-analysis-e2e-validation_{baseline_minor}_to_{target_minor}_*.json")
    ev_files = sorted(glob.glob(ev_pattern))
    if ev_files:
        reports['e2e_validation'] = ev_files[-1]

    ue_pattern = os.path.join(report_dir, f"gap-analysis-upgrade-e2e_{baseline_minor}_to_{target_minor}_*.json")
    ue_files = sorted(glob.glob(ue_pattern))
    if ue_files:
        reports['upgrade_e2e'] = ue_files[-1]

    return reports


def main():
    parser = argparse.ArgumentParser(
        description='Generate combined gap analysis report from individual reports.'
    )
    parser.add_argument('--baseline', required=True, help='Baseline version')
    parser.add_argument('--target', required=True, help='Target version')
    parser.add_argument('--report-dir',
                       default=os.environ.get('REPORT_DIR', 'reports'),
                       help='Directory to store reports (default: reports/, env: REPORT_DIR)')
    parser.add_argument('--build-log', help='Path to the build log file to parse metrics and failures')

    args = parser.parse_args()

    # Create report directory if it doesn't exist
    os.makedirs(args.report_dir, exist_ok=True)

    # Find latest reports
    reports = find_latest_reports(args.baseline, args.target, args.report_dir)

    # Determine build log path
    build_log_path = args.build_log or os.environ.get('BUILD_LOG')
    if not build_log_path:
        # Check standard candidate paths
        candidates = [
            os.path.join(args.report_dir, 'build-log.txt'),
            os.path.join(args.report_dir, '../tmp-prow-logs/build-log.txt'),
            os.path.join(args.report_dir, '../reports/build-log.txt'),
            os.path.join(os.path.dirname(args.report_dir), 'reports/build-log.txt'),
            os.path.join(os.path.dirname(args.report_dir), 'tmp-prow-logs/build-log.txt'),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                build_log_path = candidate
                break

    # Parse build log if found
    build_metrics = None
    if build_log_path and os.path.exists(build_log_path):
        log_info(f"Parsing build log: {build_log_path}")
        build_metrics = parse_build_log(build_log_path)
    else:
        log_info("No build log file found/specified. Skipping build log metrics.")

    # Load report data
    report_data = {
        'type': 'Aggregated Gap Analysis Dashboard and Build Log Summary',
        'baseline': args.baseline,
        'target': args.target,
        'timestamp': datetime.now().isoformat(),
        'build_metrics': build_metrics
    }

    # Helper to load status check data for fallback messages
    def load_status_check(check_num):
        return load_status_check_file(args.report_dir, check_num)

    def get_status_msg(check_num, default_msg):
        return get_status_message(args.report_dir, check_num, default_msg)

    def fallback_validation_result_local(check_num, default='SKIP'):
        return fallback_validation_result(args.report_dir, check_num, default)

    # Load AWS STS data
    if reports['aws_sts']:
        with open(reports['aws_sts'], 'r') as f:
            report_data['aws_sts'] = json.load(f)
        log_info(f"Loaded AWS STS report: {reports['aws_sts']}")
    else:
        err_msg = get_status_msg(1, "AWS STS script execution failed or check skipped")
        status_data = load_status_check(1) or {}
        status_errors = status_data.get('details', {}).get('errors', [])
        report_data['aws_sts'] = {
            'validation_result': 'FAIL',
            'comparison': {
                'actions': {'target_only': [], 'baseline_only': []},
                'file_changes': []
            },
            'validation_details': {
                'check_1_resources': {'status': 'FAIL', 'errors': status_errors or [err_msg], 'file_count': 0},
                'check_2_admin_ack': {'status': 'FAIL', 'errors': [], 'expected_baseline': ''}
            },
            'error_message': err_msg,
        }

    # Load GCP WIF data
    if reports['gcp_wif']:
        with open(reports['gcp_wif'], 'r') as f:
            report_data['gcp_wif'] = json.load(f)
        log_info(f"Loaded GCP WIF report: {reports['gcp_wif']}")
    else:
        err_msg = get_status_msg(2, "GCP WIF script execution failed or check skipped")
        status_data = load_status_check(2) or {}
        status_errors = status_data.get('details', {}).get('errors', [])
        report_data['gcp_wif'] = {
            'validation_result': 'FAIL',
            'comparison': {
                'actions': {'target_only': [], 'baseline_only': []},
                'file_changes': []
            },
            'validation_details': {
                'check_1_resources': {'status': 'FAIL', 'errors': status_errors or [err_msg], 'file_count': 0},
                'check_2_admin_ack': {'status': 'FAIL', 'errors': [], 'expected_baseline': ''}
            },
            'error_message': err_msg,
        }

    # Load Feature Gates data
    if reports['feature_gates']:
        with open(reports['feature_gates'], 'r') as f:
            report_data['feature_gates'] = json.load(f)
        log_info(f"Loaded Feature Gates report: {reports['feature_gates']}")
    else:
        err_msg = get_status_msg(8, "Feature Gates script execution failed or check skipped")
        report_data['feature_gates'] = {
            'validation_result': 'PASS', # feature gates is informational
            'is_z_stream': True,
            'version': args.target,
            'baseline': args.baseline,
            'target': args.target,
            'default_hypershift_gates': [],
            'total_hypershift_gates': 0,
            'error_message': err_msg
        }

    # Load OCP Gate Acknowledgment data
    if reports['ocp_gate_ack']:
        with open(reports['ocp_gate_ack'], 'r') as f:
            report_data['ocp_gate_ack'] = json.load(f)
        log_info(f"Loaded OCP Gate Acknowledgment report: {reports['ocp_gate_ack']}")
    else:
        err_msg = get_status_msg(3, "OCP Gate Acknowledgment script execution failed or check skipped")
        report_data['ocp_gate_ack'] = {
            'validation_result': 'FAIL',
            'ack_check_version': args.target,
            'summary': {
                'gates_requiring_ack': 1,
                'unacknowledged': 1,
                'ack_file_missing': True
            },
            'config_validation': {
                'valid': False,
                'errors': [err_msg]
            },
            'analysis': {
                'acknowledged_gates': [],
                'unacknowledged_gates': []
            }
        }

    # Load OCM Version Gate data
    if reports['ocm_version_gate']:
        with open(reports['ocm_version_gate'], 'r') as f:
            report_data['ocm_version_gate'] = json.load(f)
        log_info(f"Loaded OCM Version Gate report: {reports['ocm_version_gate']}")
    else:
        err_msg = get_status_msg(7, "OCM Version Gate script execution failed or check skipped")
        status_data = load_status_check(7) or {}
        status_errors = status_data.get('details', {}).get('errors', [])
        report_data['ocm_version_gate'] = {
            'validation_result': fallback_validation_result_local(7, 'FAIL'),
            'baseline_minor': extract_minor_version(args.baseline),
            'target_minor': extract_minor_version(args.target),
            'gates_count': {'baseline': 0, 'target': 0},
            'comparison': {
                'common_gates_count': 0,
                'new_gates_count': 0,
                'deprecated_gates_count': 0,
                'common_gates': [],
                'new_gates': [],
                'deprecated_gates': [],
            },
            'configuration_validation': {
                'valid': False,
                'errors': status_errors or [err_msg],
            },
            'error_message': err_msg,
        }

    # Load Versions & Channels data
    if reports['versions_channels']:
        with open(reports['versions_channels'], 'r') as f:
            report_data['versions_channels'] = json.load(f)
        log_info(f"Loaded Versions & Channels report: {reports['versions_channels']}")
    else:
        err_msg = get_status_msg(6, "Versions & Channels script execution failed or check skipped")
        status_data = load_status_check(6) or {}
        status_errors = status_data.get('details', {}).get('errors', [])
        baseline_minor = extract_minor_version(args.baseline)
        target_minor = extract_minor_version(args.target)
        report_data['versions_channels'] = {
            'validation_result': fallback_validation_result_local(6, 'FAIL'),
            'baseline': args.baseline,
            'target': args.target,
            'baseline_minor': baseline_minor,
            'target_minor': target_minor,
            'validation_errors': status_errors,
            'summary': {
                'baseline_channels': [],
                'target_channels': [],
                'target_highest_channel': status_data.get('details', {}).get('target_highest_channel'),
                'target_is_ga': status_data.get('details', {}).get('target_is_ga', False),
                'marketplace_available': status_data.get('details', {}).get('marketplace_available', False),
                'target_rosa_classic': None,
                'target_rosa_hcp': None,
                'target_osd_gcp': None,
                'gcp_skipped': status_data.get('details', {}).get('gcp_skipped', False),
            },
            'channel_availability': {
                'baseline_in_stable': status_data.get('details', {}).get('baseline_in_stable', False),
                'baseline_version_channels': [],
                'target_version_channels': [],
                'target_highest_channel': status_data.get('details', {}).get('target_highest_channel'),
                'baseline': {
                    'minor': baseline_minor,
                    'version': args.baseline,
                    'channels': {},
                },
                'target': {
                    'minor': target_minor,
                    'version': args.target,
                    'channels': {},
                },
            },
            'marketplace': {
                'available': status_data.get('details', {}).get('marketplace_available', False),
                'hcp': {
                    'baseline': {'hcp_enabled': False, 'channels': []},
                    'target': {'hcp_enabled': False, 'channels': []},
                },
            },
            'error_message': err_msg,
            'validation_errors': status_errors or [err_msg],
        }

    # Load API Resources and CRD data
    if reports['api_resources']:
        with open(reports['api_resources'], 'r') as f:
            report_data['api_resources'] = json.load(f)
        log_info(f"Loaded API Resources and CRD report: {reports['api_resources']}")
    else:
        err_msg = get_status_msg(9, "API Resources and CRD Diff Validation skipped or no snapshots found")
        report_data['api_resources'] = {
            'validation_result': fallback_validation_result_local(9),
            'summary': {
                'new_api_resources': 0,
                'removed_api_resources': 0,
                'api_version_changes': 0,
                'new_crds': 0,
                'removed_crds': 0,
                'crd_version_changes': 0,
                'deprecated_crds': 0,
                'managed_new_crds': 0,
                'managed_deprecated_crds': 0,
                'managed_removed_apis': 0,
                'compared_topologies': [],
                'skipped_topologies': ['hcp', 'classic', 'osd-gcp'],
                'compared_display_names': [],
                'skipped_display_names': ['HCP hosted (data plane)', 'Classic', 'OSD GCP'],
            },
            'topologies': [],
            'error_message': err_msg,
            'note': err_msg,
        }

    # Load Critical Alerts data
    if reports['critical_alerts']:
        with open(reports['critical_alerts'], 'r') as f:
            report_data['critical_alerts'] = json.load(f)
        log_info(f"Loaded Critical Alerts report: {reports['critical_alerts']}")
    else:
        err_msg = get_status_msg(10, "Critical Alerts Diff Validation skipped or no snapshots found")
        report_data['critical_alerts'] = {
            'validation_result': fallback_validation_result_local(10),
            'summary': {
                'new_critical': 0,
                'new_other': 0,
                'removed': 0,
                'modified': 0,
                'inherit': 0,
                'silence': 0,
                'review': 0,
                'not_applicable': 0,
                'compared_topologies': [],
                'skipped_topologies': ['hcp', 'classic', 'osd-gcp'],
                'compared_display_names': [],
                'skipped_display_names': ['HCP hosted (data plane)', 'Classic', 'OSD GCP'],
            },
            'topologies': [],
            'error_message': err_msg,
            'note': err_msg,
        }

    # Load Cluster Install data
    if reports['cluster_install']:
        with open(reports['cluster_install'], 'r') as f:
            report_data['cluster_install'] = json.load(f)
        log_info(f"Loaded Cluster Install report: {reports['cluster_install']}")
    else:
        err_msg = get_status_msg(11, "Cluster Install and Delete Validation skipped or no snapshots found")
        report_data['cluster_install'] = {
            'validation_result': fallback_validation_result_local(11),
            'summary': {
                'new_operators': 0,
                'removed_operators': 0,
                'newly_degraded': 0,
                'newly_unavailable': 0,
                'recovered_degraded': 0,
                'recovered_unavailable': 0,
                'newly_notready_nodes': 0,
                'status_changed': 0,
                'compared_topologies': [],
                'skipped_topologies': ['hcp', 'classic', 'osd-gcp'],
                'compared_display_names': [],
                'skipped_display_names': ['HCP hosted (data plane)', 'Classic', 'OSD GCP'],
            },
            'topologies': [],
            'error_message': err_msg,
            'note': err_msg,
        }

    if reports['e2e_validation']:
        with open(reports['e2e_validation'], 'r') as f:
            report_data['e2e_validation'] = json.load(f)
        log_info(f"Loaded Target E2E Validation report: {reports['e2e_validation']}")
    else:
        err_msg = get_status_msg(12, "Target E2E Validation skipped or no JUnit found")
        report_data['e2e_validation'] = {
            'validation_result': fallback_validation_result_local(12),
            'summary': {
                'tests': 0,
                'failures': 0,
                'errors': 0,
                'skipped': 0,
                'failed_count': 0,
                'compared_topologies': [],
                'skipped_topologies': ['hcp', 'classic', 'osd-gcp'],
                'compared_display_names': [],
                'skipped_display_names': ['HCP hosted (data plane)', 'Classic', 'OSD GCP'],
                'failed_topologies': [],
                'alert_monitoring_pass': 0,
                'alert_monitoring_fail': 0,
                'alert_monitoring_skip': 0,
            },
            'topologies': [],
            'error_message': err_msg,
            'note': err_msg,
        }

    if reports['upgrade_e2e']:
        with open(reports['upgrade_e2e'], 'r') as f:
            report_data['upgrade_e2e'] = json.load(f)
        log_info(f"Loaded Upgrade Validation report: {reports['upgrade_e2e']}")
    else:
        err_msg = get_status_msg(13, "Upgrade Validation skipped or no Y-1 upgrade JUnit found")
        report_data['upgrade_e2e'] = {
            'validation_result': fallback_validation_result_local(13),
            'summary': {
                'tests': 0,
                'failures': 0,
                'errors': 0,
                'skipped': 0,
                'failed_count': 0,
                'degraded_operators': 0,
                'unavailable_operators': 0,
                'duration_skip': 0,
                'pre_upgrade_skip': 0,
                'post_upgrade_fail': 0,
                'compared_topologies': [],
                'skipped_topologies': ['hcp', 'classic'],
                'compared_display_names': [],
                'skipped_display_names': ['HCP hosted (data plane)', 'Classic'],
                'failed_topologies': [],
                'e2e_categories': {
                    'workload': 0,
                    'storage': 0,
                    'network': 0,
                    'managed_operator': 0,
                    'other': 0,
                },
            },
            'topologies': [],
            'error_message': err_msg,
            'note': err_msg,
        }

    # Generate combined reports
    timestamp_suffix = f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Generate HTML report
    html_file = os.path.join(args.report_dir, f"gap-analysis-full_{args.baseline}_to_{args.target}{timestamp_suffix}.html")
    generate_html_report(report_data, html_file)
    log_success(f"Combined HTML report generated: {html_file}")

    # Generate JSON report
    json_file = os.path.join(args.report_dir, f"gap-analysis-full_{args.baseline}_to_{args.target}{timestamp_suffix}.json")
    generate_json_report(report_data, json_file)
    log_success(f"Combined JSON report generated: {json_file}")


if __name__ == '__main__':
    main()
