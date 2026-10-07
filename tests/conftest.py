import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))


def _load_script_module(module_name: str, filename: str):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


generate_combined_report = _load_script_module(
    "generate_combined_report",
    "generate-combined-report.py",
)
gap_ocm_version_gate = _load_script_module(
    "gap_ocm_version_gate",
    "gap-ocm-version-gate.py",
)
gap_ocp_gate_ack = _load_script_module(
    "gap_ocp_gate_ack",
    "gap-ocp-gate-ack.py",
)
