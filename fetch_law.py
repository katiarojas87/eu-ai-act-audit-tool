"""
Download the EU AI Act (Regulation 2024/1689) into data/eu_ai_act.txt.

Fetches the CONSOLIDATED text — the Regulation as currently in force, with every
amendment already incorporated. That matters: the Digital Omnibus on AI
(Regulation (EU) 2026/1744) deferred both high-risk deadlines and rewrote
Article 4, so the original 2024 text no longer states the law. Quoting it would
put superseded wording in a client report.

    python fetch_law.py                 # latest consolidated version
    python fetch_law.py --list          # show available consolidated versions
    python fetch_law.py --celex 02024R1689-20260727   # pin a specific one
    python fetch_law.py --original      # the 2024 act as adopted, unamended

Source: the Publications Office "Cellar" repository, which serves machine
readable text. EUR-Lex's own web pages sit behind a bot challenge (HTTP 202) and
cannot be scripted — see FALLBACK below if Cellar ever changes.

Consolidated texts carry editorial markers (▼B for the basic act, ▼M1 for text
introduced by the first amendment, ►M1 … ◄ around inline changes). Those are
stripped, so quotes read as clean legal text.

The new text is verified BEFORE it replaces the existing one: if the download is
truncated or missing provisions the tool cites, nothing is overwritten.

FALLBACK if Cellar changes: open the consolidated text in a browser (no bot
challenge there) and save it into data/ as .txt or .pdf —
    https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng  (then "consolidated")
ingest.py picks up any .pdf/.txt in data/ automatically.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date

import requests

import config

WORK_CELEX = "02024R1689"          # consolidated family for Regulation 2024/1689
ORIGINAL_CELEX = "32024R1689"      # the act as adopted
# Used only if version discovery fails; keep in step with the newest known
# consolidation so an offline-ish run still gets current law.
FALLBACK_CELEX = "02024R1689-20260727"

CELLAR = "https://publications.europa.eu/resource/celex/{celex}"
SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
HEADERS = {"Accept": "application/xhtml+xml", "Accept-Language": "eng", "User-Agent": UA}

# Provisions the rule engine cites. If any is missing the download is not usable.
REQUIRED = [
    "The following AI practices shall be prohibited",       # Art. 5
    "infer emotions of a natural person in the areas of workplace",  # Art. 5(1)(f)
    "does not pose a significant risk of harm",             # Art. 6(3)
    "recruitment or selection of natural persons",          # Annex III(4)
    "creditworthiness of natural persons",                  # Annex III(5)(b)
    "Deployers of high-risk AI systems shall take appropriate technical",  # Art. 26
    "intended to interact directly with natural persons",   # Art. 50(1)
    "technical documentation of the model",                 # Art. 53
]


def list_versions() -> list[str]:
    """Consolidated CELEX ids for this Regulation, newest first."""
    query = f"""
    PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
    SELECT DISTINCT ?celex WHERE {{
      ?w cdm:resource_legal_id_celex ?celex .
      FILTER(STRSTARTS(STR(?celex), "{WORK_CELEX}"))
    }} ORDER BY DESC(?celex)
    """
    r = requests.get(SPARQL, params={"query": query,
                                     "format": "application/sparql-results+json"},
                     headers={"Accept": "application/sparql-results+json",
                              "User-Agent": UA}, timeout=60)
    r.raise_for_status()
    return [b["celex"]["value"] for b in r.json()["results"]["bindings"]]


def latest_celex() -> str:
    try:
        versions = list_versions()
        if versions:
            return versions[0]
    except Exception as e:  # noqa: BLE001
        print(f"  version discovery failed ({type(e).__name__}); "
              f"falling back to {FALLBACK_CELEX}")
    return FALLBACK_CELEX


def strip_html(html: str) -> str:
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    # keep block boundaries as newlines so chunks stay coherent
    html = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|article|section)>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&#8217;", "'").replace("&#8220;", '"').replace("&#8221;", '"')
                .replace("&rsquo;", "'").replace("&lsquo;", "'")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def strip_consolidation_markers(text: str) -> str:
    """Remove EUR-Lex editorial marks so quotes read as plain legal text.

    ▼B / ▼M1 / ▼C1 flag which act a passage comes from; ►M1 … ◄ brackets an
    inline change. They are navigation aids, not part of the law.
    """
    text = re.sub(r"[▼►◄]\s*(?:B|M\d+|C\d+|A\d+)?", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def fetch(celex: str) -> str:
    url = CELLAR.format(celex=celex)
    print(f"Fetching {celex} from the Publications Office …")
    r = requests.get(url, timeout=120, headers=HEADERS)
    if r.status_code == 404:
        raise SystemExit(f"No such version: {celex}. Try --list.")
    r.raise_for_status()
    return strip_consolidation_markers(strip_html(r.text))


def verify(text: str) -> list[str]:
    """Return the provisions we could not find — empty means usable."""
    low = text.lower()
    return [p for p in REQUIRED if p.lower() not in low]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true",
                    help="list available consolidated versions and exit")
    ap.add_argument("--celex", help="pin a specific CELEX id")
    ap.add_argument("--original", action="store_true",
                    help="fetch the 2024 act as adopted, without amendments")
    args = ap.parse_args()

    if args.list:
        print("Consolidated versions of Regulation (EU) 2024/1689 (newest first):")
        for v in list_versions():
            print(f"  {v}")
        return 0

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    celex = args.celex or (ORIGINAL_CELEX if args.original else latest_celex())

    try:
        text = fetch(celex)
    except Exception as e:  # noqa: BLE001
        print(f"Download failed: {e}\n\n"
              "FALLBACK: open the consolidated text in your browser and save it "
              "into data/ as .txt, then run: python ingest.py\n"
              "  https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng")
        return 1

    missing = verify(text)
    if missing:
        # Refuse to replace good law with a bad download.
        print(f"REFUSING to write: {len(missing)} cited provision(s) not found in the "
              f"download ({len(text):,} chars). data/eu_ai_act.txt is unchanged.")
        for m in missing:
            print(f"  missing: {m[:70]}…")
        return 1

    out = config.DATA_DIR / "eu_ai_act.txt"
    out.write_text(text, encoding="utf-8")
    (config.DATA_DIR / "eu_ai_act.source.json").write_text(json.dumps({
        "celex": celex,
        "consolidated": not args.original and celex.startswith("0"),
        "characters": len(text),
        "fetched": date.today().isoformat(),
        "url": f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
    }, indent=2) + "\n", encoding="utf-8")

    kind = "consolidated (amendments incorporated)" if celex.startswith("0") \
        else "as adopted, WITHOUT amendments"
    print(f"Saved {len(text):,} characters to {out}")
    print(f"  version: {celex} — {kind}")
    print("Next: python ingest.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
