"""
Past data/raw/documenten_kandidaten_travel.csv aan: vervangt 16 rijen zonder bruikbare URL
(31, 32, 34, 36, 38, 40 en 41 t/m 50) door rijen die wel een URL hebben.

Gebruik (vanuit de projectmap, met venv aan):
    python scripts/patch_csv.py
"""
import csv
import shutil

PAD = "data/raw/documenten_kandidaten_travel.csv"

NIEUW = [
    ["31", "Consumenteninformatie", "Consumentenbond – Vlucht geannuleerd: rechten en keuzes", "voorlichtingspagina", "Consumentenbond", "https://www.consumentenbond.nl/juridisch-advies/vliegen-vluchtvertraging/vlucht-geannuleerd", "URL genoemd in zoekresultaat (niet zelf geopend)", "controleer datum", ""],
    ["32", "Consumenteninformatie", "Consumentenbond – Geld terug na geannuleerde vlucht", "voorlichtingspagina", "Consumentenbond", "https://www.consumentenbond.nl/juridisch-advies/vliegen-vluchtvertraging/geld-terug-na-annulering-vlucht", "URL genoemd in zoekresultaat (niet zelf geopend)", "actueel (pagina vermeldt bijgewerkt op 25 maart 2026)", ""],
    ["34", "Consumenteninformatie", "Consumentenbond – Bagage kwijt, vertraagd of beschadigd", "voorlichtingspagina", "Consumentenbond", "https://www.consumentenbond.nl/juridisch-advies/vliegen-vluchtvertraging/bagage-kwijt-vertraagd-of-beschadigd", "URL genoemd in zoekresultaat (niet zelf geopend)", "actueel (pagina vermeldt bijgewerkt op 1 juli 2026)", ""],
    ["36", "Consumenteninformatie", "Radar (AVROTROS) – Problemen met bagage: wat zijn je rechten?", "artikel", "AVROTROS Radar", "https://radar.avrotros.nl/artikel/problemen-met-bagage-wat-zijn-je-rechten-33189", "URL genoemd in zoekresultaat (niet zelf geopend)", "controleer datum", "Overlapt inhoudelijk met rij 34; handig om meerbronnen-citaties te testen"],
    ["38", "Consumenteninformatie", "BNNVARA Kassa – Check je Recht: bagage beschadigd of kwijt", "artikel", "BNNVARA Kassa", "https://www.bnnvara.nl/kassa/artikelen/check-je-recht-wat-als-je-bagage-tijdens-het-vliegen-beschadigd-raakt-of-kwijtraakt", "URL genoemd in zoekresultaat (niet zelf geopend)", "controleer datum", "Overlapt met rij 34 en 36 (bagage)"],
    ["40", "Consumenteninformatie", "Radar (AVROTROS) – Consumententip: vertraging op het vliegveld", "artikel", "AVROTROS Radar", "https://radar.avrotros.nl/artikelen/8491", "URL genoemd in zoekresultaat (niet zelf geopend)", "waarschijnlijk oud artikel (noemt aswolk-vulkaan, rond 2010); datum controleren", "Testcase voor verouderde bron"],
    ["41", "Wetgeving", "Richtlijn 2004/38/EG – vrij verkeer en verblijf van burgers van de Unie", "richtlijn", "EUR-Lex", "https://eur-lex.europa.eu/eli/dir/2004/38/oj", "ELI-patroon (nog niet geopend)", "geldig", ""],
    ["42", "Wetgeving", "Verordening (EU) 2018/1806 – lijst van visumplichtige derde landen", "verordening", "EUR-Lex", "https://eur-lex.europa.eu/eli/reg/2018/1806/oj", "ELI-patroon (nog niet geopend)", "geldig (wordt vaak gewijzigd, verifieer)", ""],
    ["43", "Wetgeving", "Verordening (EU) 2019/1157 – identiteitskaarten en verblijfsdocumenten", "verordening", "EUR-Lex", "https://eur-lex.europa.eu/eli/reg/2019/1157/oj", "ELI-patroon (nog niet geopend)", "geldig", ""],
    ["44", "Wetgeving", "Verordening (EU) 2021/953 – EU digitaal COVID-certificaat", "verordening", "EUR-Lex", "https://eur-lex.europa.eu/eli/reg/2021/953/oj", "ELI-patroon (nog niet geopend)", "verlopen (toepassing eindigde 30 juni 2023, verifieer)", "Testcase voor verouderde bron"],
    ["45", "Wetgeving", "Verordening (EG) 785/2004 – verzekeringseisen luchtvaartmaatschappijen", "verordening", "EUR-Lex", "https://eur-lex.europa.eu/eli/reg/2004/785/oj", "ELI-patroon (nog niet geopend)", "geldig", ""],
    ["46", "Wetgeving", "Verordening (EG) 593/2008 – Rome I, toepasselijk recht op overeenkomsten", "verordening", "EUR-Lex", "https://eur-lex.europa.eu/eli/reg/2008/593/oj", "ELI-patroon (nog niet geopend)", "geldig", ""],
    ["47", "Wetgeving", "Verordening (EU) 1215/2012 – bevoegdheid en erkenning (Brussel I bis)", "verordening", "EUR-Lex", "https://eur-lex.europa.eu/eli/reg/2012/1215/oj", "ELI-patroon (nog niet geopend)", "geldig", ""],
    ["48", "Wetgeving", "Richtlijn (EU) 2020/1828 – representatieve vorderingen", "richtlijn", "EUR-Lex", "https://eur-lex.europa.eu/eli/dir/2020/1828/oj", "ELI-patroon (nog niet geopend)", "geldig", ""],
    ["49", "Wetgeving", "Verordening (EU) 524/2013 – ODR-platform voor onlinegeschillen", "verordening", "EUR-Lex", "https://eur-lex.europa.eu/eli/reg/2013/524/oj", "ELI-patroon (nog niet geopend)", "waarschijnlijk ingetrokken (verifieer)", "Testcase voor verouderde bron"],
    ["50", "Wetgeving", "Richtlijn 2008/122/EG – timesharing en vakantieproducten", "richtlijn", "EUR-Lex", "https://eur-lex.europa.eu/eli/dir/2008/122/oj", "ELI-patroon (nog niet geopend)", "geldig (verifieer)", ""],
]

with open(PAD, encoding="utf-8-sig", newline="") as f:
    rijen = list(csv.reader(f, delimiter=";"))

kop, body = rijen[0], rijen[1:]
per_nr = {int(r[0]): r for r in body}

for r in NIEUW:
    per_nr[int(r[0])] = r

shutil.copy(PAD, PAD + ".bak")   # reservekopie van de oude versie
with open(PAD, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, delimiter=";")
    w.writerow(kop)
    w.writerows(per_nr[k] for k in sorted(per_nr))

zonder_url = [k for k, r in per_nr.items() if not r[5].startswith("http")]
print(f"Klaar: {len(per_nr)} rijen, zonder URL: {zonder_url or 'geen'}")