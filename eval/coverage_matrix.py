"""Decision-space coverage: what does the eval set never test?

    python eval/coverage_matrix.py                 # development set
    python eval/coverage_matrix.py --set holdout
    python eval/coverage_matrix.py --both          # union of both sets
    python eval/coverage_matrix.py --branches      # + line coverage of rules.py

The eval cases grew organically, so nobody knows which parts of the law they
exercise. An uncovered branch is legal logic that ships to clients having never
been run against a realistic description — and you cannot claim accuracy for a
rule no case has ever touched.

Two views, because they answer different questions:

  the matrix    — which legally meaningful SITUATIONS occur (every Annex III
                  domain, every role, every carve-out, every Art. 5 prohibition,
                  every tier). Gaps here are missing test cases.
  --branches    — which LINES of rules.py the set executes. Gaps here are code
                  paths no case reaches. Needs `pip install coverage`.

The matrix is the one to fix first: a covered line proves the code ran, while a
covered situation proves the law was tested.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rules import ANNEX_III_MAP, classify  # noqa: E402
from schema import Facts, HighRiskDomain  # noqa: E402

SETS = {
    "golden": Path(__file__).parent / "golden_set.json",
    "holdout": Path(__file__).parent / "holdout_set.json",
}

TIERS = ["PROHIBITED", "ANNEX_I", "ANNEX_III", "LIMITED", "MINIMAL",
         "OUT_OF_SCOPE", "NOT_AI", "UNDETERMINED"]
ROLES = ["provider", "deployer", "importer", "distributor", "unknown"]

# The carve-outs and exceptions that are this tool's whole value proposition.
# If a case never sets one, the tool's handling of it is untested against a
# realistic description no matter how many unit tests cover it.
CARVE_OUTS = [
    "biometric_verification_only", "credit_fraud_detection_only",
    "insurance_life_or_health", "art_6_3_ground",
    "military_defence_national_security", "sole_purpose_scientific_research",
    "prerelease_research_testing", "personal_non_professional_use",
    "ai_interaction_obvious", "assistive_or_no_substantial_alteration",
    "artistic_creative_satirical_work", "human_editorial_review",
    "law_enforcement_authorised_detection",
    "emotion_medical_or_safety_purpose", "biometric_lawful_dataset_filtering",
    "predictive_policing_supports_human_assessment",
    "rbi_prior_authorisation", "gpai_open_source_licence",
    "depicted_person_consented", "csam_without_right_defence",
    "sectoral_regime", "public_body_or_public_service",
]
PROHIBITIONS = [
    "subliminal_or_manipulative", "exploits_vulnerabilities", "social_scoring",
    "predictive_policing_profiling_only", "untargeted_facial_scraping",
    "biometric_categorisation_sensitive", "emotion_recognition",
    "realtime_remote_biometric_id_public_le",
    "generates_intimate_or_sexual_imagery", "generates_child_sexual_abuse_material",
]
GPAI = ["none", "uses_api", "builds_or_finetunes", "integrates_distributes"]


def _bar(hit: int, total: int, width: int = 24) -> str:
    filled = round(width * hit / total) if total else 0
    return f"[{'#' * filled}{'.' * (width - filled)}] {hit}/{total}"


def _section(title: str, items: list[str], seen: dict[str, int]) -> int:
    covered = [i for i in items if seen.get(i)]
    missing = [i for i in items if not seen.get(i)]
    print(f"\n{title}  {_bar(len(covered), len(items))}")
    for i in items:
        n = seen.get(i, 0)
        mark = f"{n:3} cases" if n else "  NEVER "
        print(f"    {'x' if n else ' '} {i:46} {mark}")
    return len(missing)


def run(cases: list[dict]) -> int:
    tiers: dict[str, int] = {}
    roles: dict[str, int] = {}
    domains: dict[str, int] = {}
    carve: dict[str, int] = {}
    prohib: dict[str, int] = {}
    gpai: dict[str, int] = {}

    for c in cases:
        exp = c["expected"]
        f = Facts.model_validate(exp)
        a = classify(f, c["name"])
        tiers[a.tier] = tiers.get(a.tier, 0) + 1
        for r in a.roles:
            roles[r] = roles.get(r, 0) + 1
        for d in f.high_risk_domains:
            domains[d] = domains.get(d, 0) + 1
        gpai[f.gpai_relationship] = gpai.get(f.gpai_relationship, 0) + 1
        # A carve-out counts as exercised only when the case actually LABELS it
        # — an unlabelled default is an assumption, not a test.
        for k in CARVE_OUTS:
            v = exp.get(k)
            if v not in (None, False, "none", "unknown") and k in exp:
                carve[k] = carve.get(k, 0) + 1
        for k in PROHIBITIONS:
            if exp.get(k) is True:
                prohib[k] = prohib.get(k, 0) + 1

    print("=" * 74)
    print(f"DECISION-SPACE COVERAGE — {len(cases)} cases")
    print("=" * 74)

    gaps = 0
    gaps += _section("TIERS", TIERS, tiers)
    gaps += _section("ROLES", ROLES, roles)
    gaps += _section("ANNEX III DOMAINS", list(ANNEX_III_MAP), domains)
    gaps += _section("GPAI RELATIONSHIPS", GPAI, gpai)
    gaps += _section("ART. 5 PROHIBITIONS (triggered by a case)", PROHIBITIONS, prohib)
    gaps += _section("CARVE-OUTS & EXCEPTIONS (explicitly labelled)", CARVE_OUTS, carve)

    total = len(TIERS) + len(ROLES) + len(ANNEX_III_MAP) + len(GPAI) \
        + len(PROHIBITIONS) + len(CARVE_OUTS)
    print("\n" + "=" * 74)
    print(f"  {total - gaps}/{total} decision situations covered — {gaps} never tested")
    print("=" * 74)
    print("\n  Each 'NEVER' is a rule the eval set has never exercised against a")
    print("  realistic description. Unit tests may cover the code; nothing covers")
    print("  the claim that the tool reaches it from a client's own words.")
    return 0


def branches(which: str) -> int:
    """Line coverage of rules.py while executing the eval set's labelled facts."""
    try:
        import coverage  # noqa: F401
    except ImportError:
        print("`coverage` is not installed.  pip install coverage")
        return 1

    driver = Path(__file__).parent / "_cov_driver.py"
    driver.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))\n"
        "from rules import classify\n"
        "from schema import Facts\n"
        f"cases = json.loads(Path(r'{SETS[which]}').read_text(encoding='utf-8'))['cases']\n"
        "for c in cases:\n"
        "    classify(Facts.model_validate(c['expected']), c['name'])\n",
        encoding="utf-8")
    try:
        root = Path(__file__).resolve().parent.parent
        subprocess.run([sys.executable, "-m", "coverage", "run",
                        "--include=src/rules.py", str(driver)], cwd=root, check=True)
        subprocess.run([sys.executable, "-m", "coverage", "report",
                        "-m", "--include=src/rules.py"], cwd=root, check=True)
        print("\n  Missing lines are decision paths the eval set never reaches.")
    finally:
        driver.unlink(missing_ok=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", dest="which", choices=sorted(SETS), default="golden")
    ap.add_argument("--both", action="store_true", help="union of both sets")
    ap.add_argument("--branches", action="store_true",
                    help="also report line coverage of rules.py")
    args = ap.parse_args()

    if args.branches:
        return branches(args.which)
    if args.both:
        cases = [c for p in SETS.values()
                 for c in json.loads(p.read_text(encoding="utf-8"))["cases"]]
    else:
        cases = json.loads(SETS[args.which].read_text(encoding="utf-8"))["cases"]
    return run(cases)


if __name__ == "__main__":
    raise SystemExit(main())
