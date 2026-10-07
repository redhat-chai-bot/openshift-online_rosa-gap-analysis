#!/usr/bin/env python3
"""Common validation functions for acknowledgment checking in managed-cluster-config."""

import json
import subprocess
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

from common import fetch_url

try:
    import yaml
except ImportError:
    raise ImportError("PyYAML not installed. Please install: pip3 install PyYAML")


# Constants
MCC_REPO_URL = "https://github.com/openshift/managed-cluster-config"
MCC_RAW_BASE_URL = "https://raw.githubusercontent.com/openshift/managed-cluster-config/master"
MCC_TREE_BASE_URL = "https://github.com/openshift/managed-cluster-config/tree/master"


def fetch_yaml_from_url(url):
    """
    Fetch and parse YAML from a URL.

    Args:
        url: URL to fetch YAML from

    Returns:
        Parsed YAML as dict/list, or None if 404

    Raises:
        HTTPError: If response is not 200 or 404
        URLError: On network errors
        yaml.YAMLError: If YAML parsing fails
    """
    try:
        return yaml.safe_load(fetch_url(url, timeout=30))
    except HTTPError as e:
        if e.code == 404:
            return None
        raise
    except URLError:
        raise
    except yaml.YAMLError:
        raise


def calculate_expected_baseline(target_version):
    """
    Calculate expected baseline version from target version.

    Args:
        target_version: Target version string (e.g., "4.21", "4.21.0", "4.21.0-ec.3")

    Returns:
        Baseline version string (e.g., "4.20")

    Examples:
        "4.21" -> "4.20"
        "4.21.5" -> "4.20"
        "4.21.0-ec.3" -> "4.20"
    """
    # Extract minor version if full version provided
    parts = target_version.split('.')
    if len(parts) < 2:
        raise ValueError(f"Invalid version format: {target_version}")

    major = int(parts[0])
    minor_part = parts[1].split('-')[0]  # Handle "21" from "4.21.0-ec.3"
    minor = int(minor_part)

    # Check for special baseline mappings (e.g., 5.0 -> 4.22, 5.1 -> 4.23)
    from openshift_releases import get_special_baseline_mapping
    target_minor = f"{major}.{minor}"
    special_baseline = get_special_baseline_mapping(target_minor)
    if special_baseline:
        return special_baseline

    baseline_minor = minor - 1
    return f"{major}.{baseline_minor}"


def fetch_managed_cluster_config_directory(resource_path, version):
    """
    Clone managed-cluster-config using sparse checkout and return file list.

    Uses git sparse checkout to efficiently fetch only the needed directory
    without cloning the entire repository.

    Args:
        resource_path: Path within repo (e.g., "resources/sts", "resources/wif")
        version: Version subdirectory (e.g., "4.21")

    Returns:
        tuple: (files_set, temp_dir_path)
            - files_set: Set of filenames in the version directory (empty set if error)
            - temp_dir_path: Path to temp directory for cleanup (None if error)

    Example:
        files, temp_dir = fetch_managed_cluster_config_directory("resources/sts", "4.21")
        # Use files...
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    """
    import tempfile
    import subprocess
    import os
    import shutil

    temp_dir = None
    files_set = set()

    try:
        # Create temporary directory
        temp_dir = tempfile.mkdtemp(prefix='mcc-checkout-')

        # Repository URL
        repo_url = "https://github.com/openshift/managed-cluster-config.git"

        # Git clone with sparse checkout
        # --filter=blob:none: Don't download file contents initially
        # --sparse: Enable sparse checkout
        # --depth 1: Only get latest commit
        clone_cmd = [
            'git', 'clone',
            '--filter=blob:none',
            '--sparse',
            '--depth', '1',
            repo_url,
            temp_dir
        ]

        result = subprocess.run(
            clone_cmd,
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            # Clone failed
            shutil.rmtree(temp_dir, ignore_errors=True)
            return (set(), None)

        # Configure sparse checkout for specific path
        sparse_checkout_cmd = [
            'git', '-C', temp_dir,
            'sparse-checkout', 'set',
            resource_path
        ]

        result = subprocess.run(
            sparse_checkout_cmd,
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            # Sparse checkout failed
            shutil.rmtree(temp_dir, ignore_errors=True)
            return (set(), None)

        # List files in the version directory
        version_dir = os.path.join(temp_dir, resource_path, version)

        if not os.path.exists(version_dir):
            # Version directory doesn't exist
            shutil.rmtree(temp_dir, ignore_errors=True)
            return (set(), None)

        # Get list of files
        try:
            entries = os.listdir(version_dir)
            files_set = set([f for f in entries if os.path.isfile(os.path.join(version_dir, f))])
        except Exception:
            # Failed to list directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            return (set(), None)

        return (files_set, temp_dir)

    except Exception as e:
        # Any other error
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        return (set(), None)


def validate_config_yaml(config_data, expected_baseline, selector_key=None, selector_value="true"):
    """
    Validate config.yaml structure and content.

    Args:
        config_data: Parsed YAML data (dict)
        expected_baseline: Expected baseline version (e.g., "4.20")
        selector_key: Optional selector key to check (e.g., "api.openshift.com/sts")
        selector_value: Expected value for selector (default: "true")

    Returns:
        Tuple of (is_valid: bool, errors: list[str], actual_baseline: str or None)
    """
    errors = []
    actual_baseline = None

    # Check deploymentMode exists
    if 'deploymentMode' not in config_data:
        errors.append("Missing required field: deploymentMode")

    # Check selectorSyncSet exists
    if 'selectorSyncSet' not in config_data:
        errors.append("Missing required field: selectorSyncSet")
        return (False, errors, actual_baseline)

    selector_sync_set = config_data['selectorSyncSet']

    # Check matchExpressions exists
    if 'matchExpressions' not in selector_sync_set:
        errors.append("Missing required field: selectorSyncSet.matchExpressions")
        return (False, errors, actual_baseline)

    match_expressions = selector_sync_set['matchExpressions']
    if not isinstance(match_expressions, list):
        errors.append("selectorSyncSet.matchExpressions must be a list")
        return (False, errors, actual_baseline)

    # Find and validate version match expression
    version_found = False
    for expr in match_expressions:
        if expr.get('key') == 'hive.openshift.io/version-major-minor':
            version_found = True
            values = expr.get('values', [])
            if not isinstance(values, list):
                errors.append("version-major-minor values must be a list")
            elif len(values) == 0:
                errors.append("version-major-minor values is empty")
            else:
                actual_baseline = values[0]
                if expected_baseline not in values:
                    errors.append(f"Baseline version mismatch: expected '{expected_baseline}', found {values}")
            break

    if not version_found:
        errors.append("Missing version match expression: hive.openshift.io/version-major-minor")

    # Check optional selector if provided
    if selector_key:
        selector_found = False
        for expr in match_expressions:
            if expr.get('key') == selector_key:
                selector_found = True
                values = expr.get('values', [])
                if selector_value not in values:
                    errors.append(f"Selector '{selector_key}' does not contain expected value '{selector_value}', found {values}")
                break

        if not selector_found:
            errors.append(f"Missing required selector: {selector_key}")

    is_valid = len(errors) == 0
    return (is_valid, errors, actual_baseline)


def validate_cloudcredential_yaml(cc_data, target_version):
    """
    Validate CloudCredential YAML structure and content.

    Args:
        cc_data: Parsed CloudCredential YAML data (dict)
        target_version: Target version (e.g., "4.21")

    Returns:
        Tuple of (is_valid: bool, errors: list[str], actual_version: str or None)
    """
    errors = []
    actual_version = None

    # Check apiVersion
    api_version = cc_data.get('apiVersion')
    if api_version != 'operator.openshift.io/v1':
        errors.append(f"Invalid apiVersion: expected 'operator.openshift.io/v1', found '{api_version}'")

    # Check kind
    kind = cc_data.get('kind')
    if kind != 'CloudCredential':
        errors.append(f"Invalid kind: expected 'CloudCredential', found '{kind}'")

    # Check patch field exists
    patch_str = cc_data.get('patch')
    if not patch_str:
        errors.append("Missing required field: patch")
        return (False, errors, actual_version)

    # Parse patch as JSON
    try:
        patch_data = json.loads(patch_str)
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON in patch field: {e}")
        return (False, errors, actual_version)

    # Extract upgradeable-to annotation
    try:
        annotations = patch_data.get('metadata', {}).get('annotations', {})
        upgradeable_to = annotations.get('cloudcredential.openshift.io/upgradeable-to')

        if not upgradeable_to:
            errors.append("Missing annotation: cloudcredential.openshift.io/upgradeable-to")
        else:
            actual_version = upgradeable_to
            expected_version = f"v{target_version}"
            if upgradeable_to != expected_version:
                errors.append(f"Version mismatch in upgradeable-to: expected '{expected_version}', found '{upgradeable_to}'")
    except (KeyError, TypeError) as e:
        errors.append(f"Error extracting upgradeable-to annotation: {e}")

    is_valid = len(errors) == 0
    return (is_valid, errors, actual_version)


def find_pr_for_file_change(file_path, target_version, changed_actions):
    """
    Find the PR that introduced changes to a specific file in managed-cluster-config.

    Uses GitHub REST API to search for recent merged PRs that likely modified the file.
    Falls back to gh CLI if GH_TOKEN is available in environment.

    Args:
        file_path: Relative path to the file (e.g., "resources/sts/4.22/sts_installer_permission_policy.json")
        target_version: Target version (e.g., "4.22")
        changed_actions: List of actions that were added/removed

    Returns:
        Tuple of (pr_url, pr_number) or (None, None) if not found
    """
    import os
    from urllib.request import Request
    from urllib.error import HTTPError, URLError
    from urllib.parse import quote_plus

    try:
        # Use GitHub REST API for unauthenticated access (60 requests/hour limit)
        # Search for merged PRs with version number in title
        # API: https://docs.github.com/en/rest/search/search?apiVersion=2022-11-28#search-issues-and-pull-requests
        query = f'{target_version} in:title repo:openshift/managed-cluster-config is:pr is:merged'
        api_url = f'https://api.github.com/search/issues?q={quote_plus(query)}&sort=updated&order=desc&per_page=20'

        # Add authentication if GH_TOKEN is available
        headers = {'Accept': 'application/vnd.github.v3+json'}
        gh_token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if gh_token:
            headers['Authorization'] = f'token {gh_token}'

        req = Request(api_url, headers=headers)
        response = urlopen(req, timeout=10)
        data = json.loads(response.read().decode('utf-8'))

        items = data.get('items', [])
        matched = _match_pr_from_search_items(items, file_path, target_version, url_key='html_url')
        if matched[0]:
            return matched

    except (HTTPError, URLError, json.JSONDecodeError, KeyError, Exception):
        # API call failed, try falling back to gh CLI if available
        pass

    # Fallback: try gh CLI if GH_TOKEN is set
    gh_token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if gh_token:
        try:
            search_query = f'is:merged {target_version} in:title'
            cmd = [
                'gh', 'pr', 'list',
                '-R', 'openshift/managed-cluster-config',
                '--search', search_query,
                '--state', 'merged',
                '--json', 'url,number,title,mergedAt',
                '--limit', '20'
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                prs = json.loads(result.stdout)
                if prs:
                    prs_sorted = sorted(prs, key=lambda x: x.get('mergedAt', ''), reverse=True)
                    return _match_pr_from_search_items(
                        prs_sorted, file_path, target_version, url_key='url'
                    )

        except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
            pass

    return (None, None)


def _match_pr_from_search_items(items, file_path, target_version, url_key='html_url'):
    """
    Select a PR from find_pr_for_file_change search results.

    Prefer filename / distinctive filename tokens in the title over a bare
    version match — many MCC PRs share the same version in the title.
    """
    if not items:
        return (None, None)

    filename = file_path.split('/')[-1].lower()
    generic = {
        'openshift', 'cloud', 'credentials', 'credential', 'policy', 'aws',
        'sts', 'wif', 'gcp', 'operator', 'installer', 'instance', 'support',
        'ocm', 'osd', 'shared', 'vpc', 'json', 'yaml',
    }
    stem = filename.replace('.json', '').replace('.yaml', '').replace('.yml', '')
    tokens = [
        part for part in stem.replace('-', '_').split('_')
        if len(part) >= 4 and part not in generic
    ]

    # 1) Exact filename in title
    for item in items:
        title = item.get('title', '').lower()
        if filename in title:
            return (item.get(url_key), item.get('number'))

    # 2) Distinctive filename token in title (e.g. 'karpenter')
    for item in items:
        title = item.get('title', '').lower()
        if any(token in title for token in tokens):
            return (item.get(url_key), item.get('number'))

    # 3) Version in title (previous behavior)
    for item in items:
        title = item.get('title', '').lower()
        if target_version in title:
            return (item.get(url_key), item.get('number'))

    # 4) Most recently updated search hit
    pr = items[0]
    return (pr.get(url_key), pr.get('number'))


def validate_sts_resources(baseline_version, target_version, expected_changes=None, baseline_cr_dir=None, target_cr_dir=None):
    """
    Validate STS policy resources in managed-cluster-config against OCP release changes.

    Dynamically discovers policy files in managed-cluster-config using git sparse checkout
    (no hardcoded lists), then validates that the ACTION changes match what's expected
    from OCP release comparison.

    Checks:
    1. Dynamically discover files via git sparse checkout of managed-cluster-config
    2. Each file is valid JSON with required structure (Version, Statement)
    3. Compare each file between baseline and target to detect changes
    4. If expected_changes provided (from OCP release), verify managed-cluster-config changes match

    Args:
        baseline_version: Baseline version (e.g., "4.20")
        target_version: Target version (e.g., "4.21")
        expected_changes: Dict with 'actions_added' and 'actions_removed' from OCP release comparison
        baseline_cr_dir: Temp directory with baseline OCP credential requests (not used for file discovery)
        target_cr_dir: Temp directory with target OCP credential requests (not used for file discovery)

    Returns:
        dict with validation results including per-file diffs
    """
    import shutil
    import os

    errors = []
    warnings = []
    warnings_structured = []  # Structured data for table rendering
    file_results = {}
    baseline_mcc_dir = None
    target_mcc_dir = None

    # Dynamically discover files in managed-cluster-config using git sparse checkout
    baseline_files, baseline_mcc_dir = fetch_managed_cluster_config_directory("resources/sts", baseline_version)
    target_files, target_mcc_dir = fetch_managed_cluster_config_directory("resources/sts", target_version)

    # Filter for JSON files only
    baseline_files = set([f for f in baseline_files if f.endswith('.json')])
    target_files = set([f for f in target_files if f.endswith('.json')])

    if not target_files:
        target_url = f"{MCC_TREE_BASE_URL}/resources/sts/{target_version}"
        errors.append(f"Target directory not found or empty in managed-cluster-config")
        errors.append(f"  Expected location: {target_url}")
        # Cleanup
        if baseline_mcc_dir:
            shutil.rmtree(baseline_mcc_dir, ignore_errors=True)
        if target_mcc_dir:
            shutil.rmtree(target_mcc_dir, ignore_errors=True)
        return {
            'valid': False,
            'errors': errors,
            'file_results': file_results,
            'changed_files': [],
            'changed_files_count': 0
        }

    # Check for files added or removed between versions.
    # New policy files are expected when OCP adds CredentialsRequests (e.g. Karpenter);
    # treat as warnings. Permission MISMATCH checks below remain the FAIL criteria.
    # Removed policy files stay errors — accidental deletion is not caught by action diffs.
    files_added = target_files - baseline_files
    files_removed = baseline_files - target_files

    if files_added:
        target_dir_url = f"{MCC_TREE_BASE_URL}/resources/sts/{target_version}"
        warnings.append("Files added in managed-cluster-config:")
        for filename in sorted(files_added):
            file_path = f"resources/sts/{target_version}/{filename}"
            pr_url, pr_number = find_pr_for_file_change(file_path, target_version, [])
            if pr_url:
                # Format: filename (MCC PR #123 @ URL) - matches unexpected-action warning style
                warnings.append(f"  • {filename} (MCC PR #{pr_number} @ {pr_url})")
            else:
                warnings.append(f"  • {filename}")
            warnings_structured.append({
                'type': 'File Added',
                'action': filename,
                'pr_number': pr_number,
                'pr_url': pr_url
            })
        warnings.append(f"  Location: {target_dir_url}")
    if files_removed:
        removed_files_list = ', '.join(sorted(files_removed))
        baseline_dir_url = f"{MCC_TREE_BASE_URL}/resources/sts/{baseline_version}"
        errors.append(f"Files removed in managed-cluster-config: {removed_files_list}")
        errors.append(f"  Previously at: {baseline_dir_url}")

    # Get all files to validate (union of both sets)
    all_files = target_files | baseline_files

    # Validate each file
    for filename in sorted(all_files):
        file_result = {
            'exists_in_baseline': filename in baseline_files,
            'exists_in_target': filename in target_files,
            'valid_json': False,
            'has_structure': False,
            'errors': []
        }

        # Only validate files that exist in target (we're validating the target version)
        if filename in target_files:
            target_file_path = os.path.join(target_mcc_dir, "resources/sts", target_version, filename)

            try:
                # Read file from local temp directory
                with open(target_file_path, 'r') as f:
                    file_data = f.read()

                # Try to parse as JSON
                try:
                    policy_json = json.loads(file_data)
                    file_result['valid_json'] = True

                    # Check for required fields
                    if 'Version' not in policy_json:
                        file_result['errors'].append("Missing 'Version' field")
                    if 'Statement' not in policy_json:
                        file_result['errors'].append("Missing 'Statement' field")

                    if 'Version' in policy_json and 'Statement' in policy_json:
                        file_result['has_structure'] = True

                        # Extract actions from target file
                        target_file_actions = set()
                        for stmt in policy_json.get('Statement', []):
                            actions = stmt.get('Action', [])
                            if isinstance(actions, str):
                                actions = [actions]
                            target_file_actions.update(actions)

                        # Read the same file from baseline version if it exists
                        baseline_file_actions = set()
                        if filename in baseline_files and baseline_mcc_dir:
                            baseline_file_path = os.path.join(baseline_mcc_dir, "resources/sts", baseline_version, filename)
                            try:
                                with open(baseline_file_path, 'r') as bf:
                                    baseline_data = bf.read()
                                baseline_json = json.loads(baseline_data)
                                for stmt in baseline_json.get('Statement', []):
                                    actions = stmt.get('Action', [])
                                    if isinstance(actions, str):
                                        actions = [actions]
                                    baseline_file_actions.update(actions)
                            except:
                                # If baseline file can't be read, treat as empty
                                pass

                        # Calculate diff
                        actions_added = sorted(target_file_actions - baseline_file_actions)
                        actions_removed = sorted(baseline_file_actions - target_file_actions)
                        file_changed = len(actions_added) > 0 or len(actions_removed) > 0

                        # Store diff information
                        file_result['file_changed'] = file_changed
                        if file_changed:
                            file_result['diff'] = {
                                'actions_added': actions_added,
                                'actions_removed': actions_removed,
                                'actions_added_count': len(actions_added),
                                'actions_removed_count': len(actions_removed)
                            }
                except json.JSONDecodeError as e:
                    file_result['errors'].append(f"Invalid JSON: {e}")
            except FileNotFoundError:
                file_result['errors'].append("File not found in checkout")
            except Exception as e:
                file_result['errors'].append(f"Error reading file: {e}")

        file_results[filename] = file_result

        # Add file-level errors to overall errors
        if file_result['errors']:
            errors.append(f"{filename}: {'; '.join(file_result['errors'])}")

    # Build summary of changed files
    changed_files = []
    for filename, file_result in file_results.items():
        if file_result.get('file_changed', False):
            changed_files.append({
                'filename': filename,
                'diff': file_result.get('diff', {}),
                'exists_in_baseline': file_result.get('exists_in_baseline', False)
            })

    # If expected_changes provided, validate that managed-cluster-config changes match OCP release changes
    if expected_changes:
        expected_added = set(expected_changes.get('actions_added', []))
        expected_removed = set(expected_changes.get('actions_removed', []))

        # Collect all actual changes from managed-cluster-config files
        actual_added = set()
        actual_removed = set()
        for changed_file in changed_files:
            diff = changed_file.get('diff', {})
            actual_added.update(diff.get('actions_added', []))
            actual_removed.update(diff.get('actions_removed', []))

        # Check for missing changes (MISMATCH - these are ERRORS that fail validation)
        missing_added = expected_added - actual_added
        missing_removed = expected_removed - actual_removed

        target_dir_url = f"{MCC_TREE_BASE_URL}/resources/sts/{target_version}"

        if missing_added:
            errors.append(f"MISMATCH: Expected actions added in OCP release but NOT found in managed-cluster-config:")
            for action in sorted(list(missing_added)[:10]):
                errors.append(f"  • {action}")
            if len(missing_added) > 10:
                errors.append(f"  ... and {len(missing_added) - 10} more missing actions")
            errors.append(f"  Review policies at: {target_dir_url}")

        if missing_removed:
            errors.append(f"MISMATCH: Expected actions removed in OCP release but NOT found removed in managed-cluster-config:")
            for action in sorted(list(missing_removed)[:10]):
                errors.append(f"  • {action}")
            if len(missing_removed) > 10:
                errors.append(f"  ... and {len(missing_removed) - 10} more missing actions")
            errors.append(f"  Review policies at: {target_dir_url}")

        # Check for unexpected changes (UNEXPECTED - these are WARNINGS, do not fail validation)
        unexpected_added = actual_added - expected_added
        unexpected_removed = actual_removed - expected_removed

        if unexpected_added or unexpected_removed:
            # Find files that have unexpected changes and get PR links
            files_with_unexpected = []
            for changed_file in changed_files:
                diff = changed_file.get('diff', {})
                file_unexpected_added = set(diff.get('actions_added', [])) - expected_added
                file_unexpected_removed = set(diff.get('actions_removed', [])) - expected_removed

                if file_unexpected_added or file_unexpected_removed:
                    filename = changed_file.get('filename')
                    file_path = f"resources/sts/{target_version}/{filename}"
                    pr_url, pr_number = find_pr_for_file_change(file_path, target_version,
                                                                 list(file_unexpected_added) + list(file_unexpected_removed))
                    files_with_unexpected.append({
                        'filename': filename,
                        'unexpected_added': sorted(list(file_unexpected_added)),
                        'unexpected_removed': sorted(list(file_unexpected_removed)),
                        'pr_url': pr_url,
                        'pr_number': pr_number
                    })

        if unexpected_added:
            # Build action-to-PR mapping for inline display
            action_to_pr = {}
            for file_info in files_with_unexpected:
                for action in file_info['unexpected_added']:
                    if action not in action_to_pr and file_info['pr_url']:
                        # Use first PR found for this action (typically same PR for all files in a version)
                        action_to_pr[action] = {
                            'pr_number': file_info['pr_number'],
                            'pr_url': file_info['pr_url']
                        }

            warnings.append(f"UNEXPECTED: Actions added in managed-cluster-config (not in OCP release):")
            for action in sorted(list(unexpected_added)[:10]):
                if action in action_to_pr:
                    pr_info = action_to_pr[action]
                    # Format: action (MCC PR #123 @ URL) - template will parse this
                    warnings.append(f"  • {action} (MCC PR #{pr_info['pr_number']} @ {pr_info['pr_url']})")
                    # Add structured data for table rendering
                    warnings_structured.append({
                        'type': 'Added',
                        'action': action,
                        'pr_number': pr_info['pr_number'],
                        'pr_url': pr_info['pr_url']
                    })
                else:
                    warnings.append(f"  • {action}")
                    # Add structured data without PR link
                    warnings_structured.append({
                        'type': 'Added',
                        'action': action,
                        'pr_number': None,
                        'pr_url': None
                    })
            if len(unexpected_added) > 10:
                warnings.append(f"  ... and {len(unexpected_added) - 10} more unexpected actions")
            warnings.append(f"  Review policies at: {target_dir_url}")

        if unexpected_removed:
            # Build action-to-PR mapping for inline display
            action_to_pr = {}
            for file_info in files_with_unexpected:
                for action in file_info['unexpected_removed']:
                    if action not in action_to_pr and file_info['pr_url']:
                        # Use first PR found for this action (typically same PR for all files in a version)
                        action_to_pr[action] = {
                            'pr_number': file_info['pr_number'],
                            'pr_url': file_info['pr_url']
                        }

            warnings.append(f"UNEXPECTED: Actions removed in managed-cluster-config (not in OCP release):")
            for action in sorted(list(unexpected_removed)[:10]):
                if action in action_to_pr:
                    pr_info = action_to_pr[action]
                    # Format: action (MCC PR #123 @ URL) - template will parse this
                    warnings.append(f"  • {action} (MCC PR #{pr_info['pr_number']} @ {pr_info['pr_url']})")
                    # Add structured data for table rendering
                    warnings_structured.append({
                        'type': 'Removed',
                        'action': action,
                        'pr_number': pr_info['pr_number'],
                        'pr_url': pr_info['pr_url']
                    })
                else:
                    warnings.append(f"  • {action}")
                    # Add structured data without PR link
                    warnings_structured.append({
                        'type': 'Removed',
                        'action': action,
                        'pr_number': None,
                        'pr_url': None
                    })
            if len(unexpected_removed) > 10:
                warnings.append(f"  ... and {len(unexpected_removed) - 10} more unexpected actions")
            warnings.append(f"  Review policies at: {target_dir_url}")

    # Validation passes if no ERRORS (MISMATCH), but can have WARNINGS (UNEXPECTED)
    is_valid = len(errors) == 0

    # Return with changed files summary, errors, and warnings
    result = {
        'valid': is_valid,
        'errors': errors,
        'warnings': warnings,
        'warnings_structured': warnings_structured,  # Structured data for table rendering
        'file_results': file_results,
        'changed_files': changed_files,
        'changed_files_count': len(changed_files)
    }

    # Cleanup temp directories
    if baseline_mcc_dir:
        shutil.rmtree(baseline_mcc_dir, ignore_errors=True)
    if target_mcc_dir:
        shutil.rmtree(target_mcc_dir, ignore_errors=True)

    return result


def validate_wif_resources(target_version, added_actions=None):
    """
    Validate WIF resources directory and vanilla.yaml file.

    Uses git sparse checkout to fetch only the needed directory from managed-cluster-config.

    Checks:
    1. Directory exists at resources/wif/{version}/
    2. vanilla.yaml exists
    3. File is valid YAML
    4. Has required fields (id, kind, service_accounts)
    5. If added_actions provided, verify they exist in service account roles

    Args:
        target_version: Target version (e.g., "4.21")
        added_actions: Optional list of GCP permissions that were added (e.g., ["compute.instances.create"])

    Returns:
        Dict with validation results including actions found in roles
    """
    import shutil
    import os

    errors = []
    file_data = None
    mcc_dir = None

    # Use git sparse checkout to fetch resources/wif directory
    files, mcc_dir = fetch_managed_cluster_config_directory("resources/wif", target_version)

    if not files or 'vanilla.yaml' not in files:
        vanilla_url = f"{MCC_TREE_BASE_URL}/resources/wif/{target_version}/vanilla.yaml"
        errors.append(f"vanilla.yaml not found in managed-cluster-config")
        errors.append(f"  Expected location: {vanilla_url}")
        if mcc_dir:
            shutil.rmtree(mcc_dir, ignore_errors=True)
        return {
            'valid': False,
            'errors': errors,
            'file_data': file_data,
            'actions_found_in_roles': {},
            'missing_actions': []
        }

    # Read vanilla.yaml from local checkout
    vanilla_yaml_path = os.path.join(mcc_dir, "resources/wif", target_version, "vanilla.yaml")

    try:
        with open(vanilla_yaml_path, 'r') as f:
            vanilla_yaml = yaml.safe_load(f)

        file_data = vanilla_yaml

        # Check required fields
        if 'id' not in vanilla_yaml:
            errors.append("vanilla.yaml missing required field: 'id'")
        else:
            # Verify id matches version
            expected_id = f"v{target_version}"
            if vanilla_yaml['id'] != expected_id:
                errors.append(f"vanilla.yaml id mismatch: expected '{expected_id}', found '{vanilla_yaml['id']}'")

        if 'kind' not in vanilla_yaml:
            errors.append("vanilla.yaml missing required field: 'kind'")
        elif vanilla_yaml['kind'] != 'WifTemplate':
            errors.append(f"vanilla.yaml kind should be 'WifTemplate', found '{vanilla_yaml['kind']}'")

        service_accounts_valid = True
        if 'service_accounts' not in vanilla_yaml:
            errors.append("vanilla.yaml missing required field: 'service_accounts'")
            service_accounts_valid = False
        elif not isinstance(vanilla_yaml['service_accounts'], list):
            errors.append("vanilla.yaml 'service_accounts' should be a list")
            service_accounts_valid = False
        elif len(vanilla_yaml['service_accounts']) == 0:
            errors.append("vanilla.yaml 'service_accounts' is empty")
            service_accounts_valid = False

        # If added_actions provided and service_accounts valid, check for them
        actions_found_in_roles = {}
        missing_actions = []

        if added_actions and service_accounts_valid:
            all_permissions = set()

            # Extract all permissions from all service accounts
            for sa in vanilla_yaml.get('service_accounts', []):
                sa_id = sa.get('id', 'unknown')
                for role in sa.get('roles', []):
                    role_id = role.get('id', 'unknown')
                    permissions = role.get('permissions', [])

                    for perm in permissions:
                        all_permissions.add(perm)
                        # Track which actions are in which roles
                        if perm in added_actions:
                            if perm not in actions_found_in_roles:
                                actions_found_in_roles[perm] = []
                            actions_found_in_roles[perm].append(f"{sa_id}/{role_id}")

            missing_actions = sorted(set(added_actions) - all_permissions)
            if missing_actions:
                vanilla_url = f"{MCC_TREE_BASE_URL}/resources/wif/{target_version}/vanilla.yaml"
                errors.append(f"MISMATCH: Added GCP permissions NOT found in vanilla.yaml:")
                for action in missing_actions[:10]:
                    errors.append(f"  • {action}")
                if len(missing_actions) > 10:
                    errors.append(f"  ... and {len(missing_actions) - 10} more missing permissions")
                errors.append(f"  Review vanilla.yaml at: {vanilla_url}")

    except yaml.YAMLError as e:
        errors.append(f"vanilla.yaml is not valid YAML: {e}")
    except Exception as e:
        errors.append(f"Error validating vanilla.yaml: {e}")

    is_valid = len(errors) == 0

    # Enhanced return with action tracking
    result = {
        'valid': is_valid,
        'errors': errors,
        'file_data': file_data,
        'actions_found_in_roles': actions_found_in_roles,
        'missing_actions': missing_actions
    }

    # Cleanup temp directory
    if mcc_dir:
        shutil.rmtree(mcc_dir, ignore_errors=True)

    return result
