import csv
import shutil

PAD = "data/raw/documenten_kandidaten_travel.csv"

NIEUW = [
    ["38", "Wetgeving", "Verordening (EU) 2017/1128 – overdraagbaarheid van onlinecontentdiensten", "verordening", "EUR-Lex", "https://eur-lex.europa.eu/eli/reg/2017/1128/oj", "ELI-patroon (nog niet geopend)", "geldig", "Vervangt BNNVARA-pagina (gaf 404)"],
    ["41", "Wetgeving", "Verordening (EU) 2021/1230 – grensoverschrijdende betalingen", "verordening", "EUR-Lex", "https://eur-lex.europa.eu/eli/reg/2021/1230/oj", "ELI-patroon (nog niet geopend)", "geldig", "Vervangt Richtlijn 2004/38 (niet beschikbaar via CELLAR)"],
]

with open(PAD, encoding="utf-8-sig", newline="") as f:
    rijen = list(csv.reader(f, delimiter=";"))

kop, body = rijen[0], rijen[1:]
per_nr = {int(r[0]): r for r in body}

for r in NIEUW:
    per_nr[int(r[0])] = r

shutil.copy(PAD, PAD + ".bak")
with open(PAD, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(kop)
    w.writerows(per_nr[k] for k in sorted(per_nr))

zonder_url = [k for k, r in per_nr.items() if not r[5].startswith("http")]
print(f"Klaar: {len(per_nr)} rijen, zonder URL: {zonder_url or 'geen'}")