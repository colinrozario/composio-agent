"""Cross-platform pipeline runner (Windows has no `make`). Usage: python run.py <step> [slugs...]
Steps: catalog, pass1, verify, sample, grade, site, all, serve, smoke"""
import subprocess, sys
from pathlib import Path

SRC = Path(__file__).parent/"src"
STEPS = {
    "catalog": ["pass0_composio.py"],
    "pass1":   ["pass1_research.py"],
    "verify":  ["pass2_linkcheck.py", "pass2_oracle.py", "pass2_grounded.py", "pass2_rephrased.py", "merge.py", "pass2_oracle.py"],
    "sample":  ["sample.py"],
    "grade":   ["grade.py"],
    "site":    ["merge.py", "cluster.py", "build_site.py"],
}
STEPS["all"] = STEPS["catalog"] + STEPS["pass1"] + STEPS["verify"] + STEPS["sample"]

def main():
    step, extra = (sys.argv[1] if len(sys.argv) > 1 else "help"), sys.argv[2:]
    if step == "serve":
        return subprocess.run([sys.executable, "-m", "http.server", "8000"], cwd=Path(__file__).parent/"site").returncode
    if step == "smoke":
        step, extra = "pass1", extra or ["salesforce", "sherlock", "paygent_connect"]
    if step not in STEPS: sys.exit(__doc__)
    for script in STEPS[step]:
        args = extra if script in ("pass1_research.py", "pass2_grounded.py", "pass2_rephrased.py") else []
        print(f"\n== {script} {' '.join(args)}")
        if subprocess.run([sys.executable, script, *args], cwd=SRC).returncode: sys.exit(f"{script} failed")

if __name__ == "__main__": main()
