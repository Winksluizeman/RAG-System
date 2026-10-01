"""
Hulpmiddel voor de testvragen.

  python scripts/snippets.py zoek "7 dagen"      # in welke documenten staat deze tekst? (met omringende zin)
  python scripts/snippets.py check               # controleert of alle gold_snippets in queries.json bestaan

Vergelijking gebeurt zoals in het labscript: hoofdletters en witruimte tellen niet mee.
"""
import json
import re
import sys
from pathlib import Path

DATA_DIR = Path("data/markdown")
QUERIES = Path("queries.json")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def load() -> dict:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(DATA_DIR.glob("*.md"))}


def zoek(term: str, context: int = 100, per_doc: int = 2) -> None:
    n = norm(term)
    hits = 0
    for doc, text in load().items():
        flat = norm(text)
        found = list(re.finditer(re.escape(n), flat))
        if not found:
            continue
        hits += 1
        print(f"\n[{doc[:2]}] {doc[3:60]}  ({len(found)}x)")
        for m in found[:per_doc]:
            s, e = max(0, m.start() - context), min(len(flat), m.end() + context)
            print(f"   ...{flat[s:e]}...")
    print(f"\n{hits} document(en) bevatten '{term}'")


def check() -> None:
    docs = {d: norm(t) for d, t in load().items()}
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))
    problemen = 0
    for q in queries:
        print(f"\n{q['id']}: {q['query']}")
        if not q.get("answerable", True):
            print("   edge case zonder antwoord: geen snippets nodig")
            continue
        snippets = q.get("gold_snippets", [])
        if not snippets or any(not s.strip() for s in snippets):
            print("   !! nog geen snippet ingevuld")
            problemen += 1
            continue
        for s in snippets:
            n = norm(s)
            woorden = len(n.split())
            gevonden = [d[:2] for d, t in docs.items() if n in t]
            opm = "" if 5 <= woorden <= 14 else f"  (let op: {woorden} woorden, ideaal 5-12)"
            if gevonden:
                print(f"   OK  '{s}' -> documenten {gevonden}{opm}")
            else:
                print(f"   NIET GEVONDEN: '{s}'{opm}")
                problemen += 1
    print(f"\n{problemen} probleem/problemen")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "zoek":
        zoek(" ".join(sys.argv[2:]))
    elif len(sys.argv) >= 2 and sys.argv[1] == "check":
        check()
    else:
        print(__doc__)