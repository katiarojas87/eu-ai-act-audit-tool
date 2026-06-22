"""
Download the EU AI Act (Regulation 2024/1689) full text into data/eu_ai_act.txt.

EUR-Lex and the Publications Office block scripted access (HTTP 202/403 bot
challenge), so we pull the complete consolidated text from a reliable public
mirror instead. After running this, run `python ingest.py`.

    python fetch_law.py

FALLBACK if the mirror ever changes: open the official text in your browser
(no bot challenge there) and save it into data/ as a .pdf or .txt:
    https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng
ingest.py picks up any .pdf/.txt files in data/ automatically.
"""
import re
import sys

import requests

import config

SOURCE = "https://www.aiact-info.eu/full-text-and-pdf-download/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def strip_html(html: str) -> str:
    html = re.sub(r"(?is)<script.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?</style>", " ", html)
    # keep block boundaries as newlines so chunks stay coherent
    html = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|article|section)>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&#8217;", "'").replace("&#8220;", '"').replace("&#8221;", '"')
                .replace("&rsquo;", "'").replace("&lsquo;", "'"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def main() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading EU AI Act full text from {SOURCE} ...")
    try:
        r = requests.get(SOURCE, timeout=90, headers=HEADERS)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"Download failed: {e}\n\n"
              "FALLBACK: open this in your browser and save the text/PDF into data/:\n"
              "  https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng\n"
              "then run: python ingest.py")
        sys.exit(1)

    text = strip_html(r.text)
    if "annex iii" not in text.lower() or "creditworthiness" not in text.lower():
        print("WARNING: downloaded text looks incomplete — verify data/eu_ai_act.txt "
              "or use the EUR-Lex browser fallback noted in this script's docstring.")

    out = config.DATA_DIR / "eu_ai_act.txt"
    out.write_text(text, encoding="utf-8")
    print(f"Saved {len(text):,} characters to {out}")
    print("Next: python ingest.py")


if __name__ == "__main__":
    main()
