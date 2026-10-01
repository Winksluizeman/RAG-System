"""
Downloadt de documenten uit documenten_kandidaten_travel.csv en zet ze om naar Markdown.

Installatie:
    pip install curl_cffi beautifulsoup4 html2text

Gebruik:
    python download_documents.py            # slaat bestaande bestanden over
    python download_documents.py --force    # downloadt alles opnieuw

Uitvoer:
    data/markdown/NN_titel.md   (één bestand per document, met #-koppen)
    data/manifest.csv           (bron, ophaaldatum, grootte, aantal koppen, status)
"""
import argparse
import csv
import os
import re
import time
from datetime import datetime
from urllib.parse import quote, unquote

import html2text
from bs4 import BeautifulSoup
from curl_cffi import requests

SCRIPT_VERSION = "2026-09-30 concordantietabellen overslaan"
CSV_PATH = "data/raw/documenten_kandidaten_travel.csv"
OUTPUT_DIR = "data/markdown"
MANIFEST_PATH = "data/manifest.csv"
MIN_WORDS = 300  # kleiner dan dit = waarschijnlijk leeg of alleen een cookiebanner

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------------------------------------------------
# Identifier / URL helpers
# ---------------------------------------------------------

def eli_to_celex(eli_path: str) -> str:
    """reg/2004/261/oj -> 32004R0261 ; dir/2015/2302/oj -> 32015L2302"""
    match = re.fullmatch(r"(reg|dir)/(\d{4})/(\d+)/oj", eli_path.strip("/"))
    if not match:
        raise ValueError(f"Onbekend ELI-formaat: {eli_path}")
    doc_type, year, number = match.groups()
    letter = {"reg": "R", "dir": "L"}[doc_type]
    return f"3{year}{letter}{int(number):04d}"


def is_eurlex(url: str) -> bool:
    return "eur-lex.europa.eu" in url


def build_download_url(url: str) -> str:
    """EUR-Lex (ELI- of CELEX-link) -> CELLAR resource URL. Andere URL's blijven ongewijzigd."""
    if "eur-lex.europa.eu/eli/" in url:
        eli_path = url.split("/eli/", 1)[1].rstrip("/")
        eli_path = re.sub(r"/(html|nld|eng)$", "", eli_path)
        return f"https://publications.europa.eu/resource/celex/{eli_to_celex(eli_path)}"

    if is_eurlex(url):
        m = re.search(r"CELEX:([0-9A-Z()]+)", unquote(url), re.IGNORECASE)
        if m:
            return f"https://publications.europa.eu/resource/celex/{quote(m.group(1))}"

    return url


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[^\w\s-]", "", str(name)).strip().lower()
    return re.sub(r"[-\s]+", "_", name)[:80]


# ---------------------------------------------------------
# HTML -> Markdown
# ---------------------------------------------------------

# EUR-Lex gebruikt <p class="..."> in plaats van <h2>/<h3>. Deze klassen zetten we om.
EURLEX_H2 = "p.oj-ti-section-1, p.ti-section-1, p.title-division-1"
EURLEX_H3 = "p.oj-ti-art, p.ti-art, p.title-article-norm"

# Tweede vangnet: herken kopregels aan hun tekst, ongeacht de HTML-opmaak
# (oudere teksten gebruiken andere tags, bijvoorbeeld <p><b>Artikel 1</b></p> of tabelcellen).
ARTICLE_RE = re.compile(r"artikel\s+\d+[a-z]?(\s+(bis|ter|quater|quinquies|sexies))?\.?", re.I)
CHAPTER_RE = re.compile(r"(hoofdstuk|afdeling|titel|deel)\s+([ivxlcdm]+|\d+)\.?", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _is_concordance_table(table) -> bool:
    """Tabel die oude en nieuwe artikelen naast elkaar zet ("Artikel 5 | Artikel 7"):
    minstens één rij met twee of meer cellen die met 'Artikel' beginnen."""
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        hits = sum(1 for c in cells if _norm(c.get_text(" ", strip=True)).lower().startswith("artikel"))
        if hits >= 2:
            return True
    return False


def promote_headings_by_text(soup) -> None:
    concordance = {}  # cache per tabel
    for el in soup.find_all(["p", "div", "td", "th"]):
        if el.find_parent(["h1", "h2", "h3", "h4"]):
            continue
        table = el.find_parent("table")
        if table is not None:
            key = id(table)
            if key not in concordance:
                concordance[key] = _is_concordance_table(table)
            if concordance[key]:
                continue  # geen kopjes uit concordantietabellen
        if el.find(["p", "div", "table"]):  # houder, geen losse regel
            continue
        text = _norm(el.get_text(" ", strip=True))
        if ARTICLE_RE.fullmatch(text):
            level = "h3"
        elif CHAPTER_RE.fullmatch(text):
            level = "h2"
        else:
            continue
        new = soup.new_tag(level)
        new.string = text
        if el.name in ("td", "th"):
            el.clear()
            el.append(new)
        else:
            el.replace_with(new)


def clean_and_format_html_to_md(html_content: str, title: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")

    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()

    # 1) Koppen via bekende EUR-Lex class-namen
    for p in soup.select(EURLEX_H2):
        p.name = "h2"
    for p in soup.select(EURLEX_H3):
        p.name = "h3"

    # 2) Koppen via de tekst zelf ("Artikel 5", "HOOFDSTUK II")
    promote_headings_by_text(soup)

    # Bij gewone websites alleen de hoofdinhoud (scheelt cookiebanners en menu's)
    root = soup.find("main") or soup.find("article") or soup.body or soup

    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.body_width = 0
    markdown = h.handle(str(root))

    # 3) Laatste vangnet op Markdown-niveau (ook "**Artikel 1**" en afwijkende spaties)
    if not re.search(r"^#{2,6}\s", markdown, re.MULTILINE):
        markdown = re.sub(
            r"^[\s*_]*(Artikel\s+\d+\w*)[\s*_]*$", r"### \1", markdown,
            flags=re.MULTILINE | re.IGNORECASE,
        )

    # 4) Titel van het artikel aan de kop plakken: "### Artikel 1 – Onderwerp"
    markdown = re.sub(
        r"^(###[^\S\n]+Artikel[^\n]*?)[^\S\n]*\n[^\S\n]*\n(?![\d(#\\\-|—–])\*{0,2}([^\n*]{2,120}?)\*{0,2}[^\S\n]*\n",
        r"\1 – \2\n", markdown, flags=re.MULTILINE,
    )

    return f"# {title}\n\n{markdown.strip()}\n"


def count_headings(md: str) -> int:
    return len(re.findall(r"^#{2,6}\s", md, re.MULTILINE))


# ---------------------------------------------------------
# HTTP
# ---------------------------------------------------------

RETRY_STATUS = {202, 429, 500, 502, 503, 504}


def http_get(url: str, headers: dict, tries: int = 3):
    """GET met een paar pogingen. 202 is bij EUR-Lex een bot-controle, geen document."""
    response = None
    for attempt in range(1, tries + 1):
        try:
            response = requests.get(
                url, headers=headers, impersonate="chrome",
                timeout=45, allow_redirects=True,
            )
            print(
                f"    HTTP {response.status_code} | "
                f"type={response.headers.get('content-type')} | bytes={len(response.content)}"
            )
            if response.status_code not in RETRY_STATUS:
                return response
        except Exception as e:
            print(f"    [!] Verzoek mislukt: {e}")
            response = None
        if attempt < tries:
            time.sleep(2 * attempt)
    return response


def download_url(url: str):
    """
    Geeft (response, gebruikte_url) terug; response is None bij mislukken.
    EUR-Lex: CELLAR (XHTML, dan HTML), daarna gewone EUR-Lex-pagina als laatste redmiddel.
    """
    base_headers = {"User-Agent": USER_AGENT}
    target_url = build_download_url(url)

    if not is_eurlex(url):
        return http_get(target_url, base_headers), target_url

    for mime_type in ("application/xhtml+xml", "text/html"):
        headers = {
            **base_headers,
            "Accept": mime_type,
            "Accept-Language": "nld",
            "Accept-Max-Cs-Size": "52428800",
        }
        print(f"    CELLAR request: {mime_type}")
        response = http_get(target_url, headers)
        if response is not None and response.status_code == 200:
            return response, target_url

    m = re.search(r"/resource/celex/([^/?]+)", target_url, re.IGNORECASE)
    if m:
        celex = unquote(m.group(1))
        fallback = (
            "https://eur-lex.europa.eu/legal-content/NL/TXT/HTML/"
            f"?uri=CELEX:{quote(celex)}"
        )
        print(f"    Fallback EUR-Lex: {fallback}")
        response = http_get(fallback, base_headers)
        if response is not None and response.status_code == 200:
            return response, fallback

    return None, target_url


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="bestaande bestanden opnieuw downloaden")
    args = parser.parse_args()

    print(f"--- Starten met downloaden (scriptversie: {SCRIPT_VERSION}) ---")
    if not os.path.exists(CSV_PATH):
        print(f"[!] Fout: kan {CSV_PATH} niet vinden.")
        return

    manifest = []

    with open(CSV_PATH, mode="r", encoding="utf-8-sig", errors="ignore") as f:
        rows = list(csv.DictReader(f, delimiter=";"))

    for row in rows:
        nr = row.get("nr", "").strip()
        titel = row.get("titel", f"document_{nr}").strip()
        url = str(row.get("bron_url_of_zoekterm", "")).strip()

        entry = {
            "nr": nr, "titel": titel, "bestand": "", "bron_url": url, "gebruikte_url": "",
            "categorie": row.get("categorie", ""), "type": row.get("type", ""),
            "organisatie": row.get("organisatie", ""), "status_bron": row.get("status", ""),
            "ophaaldatum": "", "woorden": 0, "koppen": 0, "resultaat": "",
        }
        manifest.append(entry)

        if not url.startswith("http"):
            print(f"[-] Overslaan [{nr}]: geen directe URL ('{url}')")
            entry["resultaat"] = "geen_url"
            continue

        try:
            filename = f"{int(nr):02d}_{sanitize_filename(titel)}.md"
        except ValueError:
            filename = f"{sanitize_filename(titel)}.md"
        filepath = os.path.join(OUTPUT_DIR, filename)
        entry["bestand"] = filename

        print()
        print("=" * 80)
        print(f"[+] Verwerken [{nr}]: {titel}")

        if os.path.exists(filepath) and not args.force:
            with open(filepath, encoding="utf-8") as existing:
                md = existing.read()
            entry.update(
                resultaat="bestaat_al", woorden=len(md.split()), koppen=count_headings(md),
                ophaaldatum=datetime.fromtimestamp(os.path.getmtime(filepath)).strftime("%Y-%m-%d"),
            )
            print(f"    [=] Bestaat al, overgeslagen ({entry['woorden']} woorden)")
            continue

        response, used_url = download_url(url)
        entry["gebruikte_url"] = used_url

        if response is None or response.status_code != 200:
            code = response.status_code if response is not None else "geen_antwoord"
            entry["resultaat"] = f"mislukt_http_{code}"
            print(f"    [!] Mislukt ({code})")
            if response is not None:
                debug_path = filepath + ".error.html"
                try:
                    with open(debug_path, "w", encoding="utf-8") as d:
                        d.write(response.text)
                    print(f"    -> Debugbestand: {debug_path}")
                except Exception as e:
                    print(f"    [!] Kon debugbestand niet opslaan: {e}")
            continue

        content_type = (response.headers.get("content-type") or "").lower()
        if "pdf" in content_type:
            entry["resultaat"] = "pdf_niet_ondersteund"
            print("    [!] Dit is een PDF; download handmatig of gebruik een PDF-lezer.")
            continue

        try:
            md = clean_and_format_html_to_md(response.text, titel)
            with open(filepath, "w", encoding="utf-8") as out:
                out.write(md)
        except Exception as e:
            entry["resultaat"] = "fout_bij_omzetten"
            print(f"    [!] Fout bij verwerken van HTML: {e}")
            continue

        words, heads = len(md.split()), count_headings(md)
        entry.update(
            woorden=words, koppen=heads,
            ophaaldatum=datetime.now().strftime("%Y-%m-%d"),
            resultaat="te_klein" if words < MIN_WORDS else "ok",
        )
        print(f"    -> Opgeslagen: {filename} ({words} woorden, {heads} koppen)")
        if words < MIN_WORDS:
            print("    [!] Erg kort: waarschijnlijk met JavaScript geladen. Kopieer de tekst handmatig.")
        elif is_eurlex(url) and heads == 0:
            print("    [!] Geen koppen gevonden: controleer de class-namen (zie uitleg).")

        time.sleep(0.5)  # rustig aan richting servers

    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, "w", newline="", encoding="utf-8-sig") as mf:
        writer = csv.DictWriter(mf, fieldnames=list(manifest[0].keys()), delimiter=";")
        writer.writeheader()
        writer.writerows(manifest)

    ok = sum(m["resultaat"] in ("ok", "bestaat_al") for m in manifest)
    print()
    print(f"Klaar: {ok}/{len(manifest)} documenten aanwezig. Manifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()