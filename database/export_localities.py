"""
Exporte le découpage administratif du Burkina Faso vers
integrations/data/localities.json.

POURQUOI. En production, NetXMS est lu par son API Web, qui ne donne pas accès
au référentiel propre à l'agence (schéma `donnebase` de la base NetXMS). Pour
placer un équipement dans sa province et sa région, le connecteur API
(integrations/netxms.py) se sert donc :

  * de la ville de l'objet NetXMS (adresse postale), traduite en province et
    région par la table ville -> commune -> province -> région du référentiel ;
  * à défaut, de sa géolocalisation, placée dans le polygone de sa région.

Ce script fige ces deux tables dans un fichier versionné. Il ne s'exécute
qu'une fois, ou quand le référentiel change : la production n'a besoin ni du
dump ni de la base. Le contenu est du découpage administratif public (noms de
villes, provinces, régions et contours des régions), sans aucune donnée
d'équipement ni de site.

Usage, depuis la racine du dépôt :

    python database/export_localities.py database/netxmsbd07082026.sql

Le contour des régions vient de frontend/public/regions-simplified.geojson,
déjà servi au navigateur pour la carte.
"""
from __future__ import annotations

import collections
import json
import sys
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "integrations" / "data" / "localities.json"
REGION_SHAPES = ROOT / "frontend" / "public" / "regions-simplified.geojson"

TABLES = {
    "donnebase.ville": ("id_ville", "id_commune", "nomville"),
    "donnebase.limitecommune": ("id_lcommune", "id_lprovince"),
    "donnebase.limiteprovince": ("id_lprovince", "id_lregion", "nomprovince"),
    "donnebase.limiteregion": ("id_lregion", "nomregion", "Nouveau"),
}
NULL = "\\N"


def key(name: str) -> str:
    """Clé de rapprochement : majuscules, sans accents ni séparateurs."""
    text = unicodedata.normalize("NFD", name or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.upper().replace("-", " ").replace("_", " ").split())


def read_tables(dump_path: str) -> dict[str, list[dict]]:
    """Lit les blocs COPY des quatre tables, sans base de données."""
    rows: dict[str, list[dict]] = collections.defaultdict(list)
    current = None
    with open(dump_path, encoding="utf8") as dump:
        for line in dump:
            if current is None:
                if line.startswith("COPY "):
                    table = line.split()[1]
                    if table in TABLES:
                        header = line[line.index("(") + 1:line.index(")")]
                        current = (table, [c.strip().strip('"') for c in header.split(",")])
                continue
            if line.startswith("\\."):
                current = None
                continue
            table, columns = current
            values = dict(zip(columns, line.rstrip("\n").split("\t")))
            rows[table].append(
                {name: (None if values.get(name) in (None, NULL) else values[name])
                 for name in TABLES[table]}
            )
    missing = [table for table in TABLES if not rows.get(table)]
    if missing:
        sys.exit(f"Tables absentes du dump : {', '.join(missing)}")
    return rows


def cities(rows: dict[str, list[dict]]) -> dict[str, list[str]]:
    """Ville -> [province, région]. Une ville homonyme dans deux provinces est
    écartée : la même règle que le connecteur base (integrations/netxms_db.py)."""
    communes = {r["id_lcommune"]: r["id_lprovince"] for r in rows["donnebase.limitecommune"]}
    provinces = {r["id_lprovince"]: r for r in rows["donnebase.limiteprovince"]}
    regions = {
        r["id_lregion"]: (r["Nouveau"] or r["nomregion"])
        for r in rows["donnebase.limiteregion"]
    }
    found: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    for ville in rows["donnebase.ville"]:
        province = provinces.get(communes.get(ville["id_commune"]))
        if not ville["nomville"] or province is None:
            continue
        region = regions.get(province["id_lregion"])
        if region:
            found[key(ville["nomville"])].add((province["nomprovince"], region))
    return {name: list(next(iter(places))) for name, places in sorted(found.items())
            if len(places) == 1}


def region_shapes(rows: dict[str, list[dict]]) -> list[dict]:
    """Contours des régions, nommés comme dans le référentiel (« Nouveau »)."""
    names = {key(r["Nouveau"]): r["Nouveau"] for r in rows["donnebase.limiteregion"] if r["Nouveau"]}
    shapes = []
    features = json.loads(REGION_SHAPES.read_text(encoding="utf8"))["features"]
    for feature in features:
        label = feature["properties"].get("nom") or ""
        name = names.get(key(label))
        if name is None:
            sys.exit(f"Région « {label} » du fond de carte absente du référentiel")
        geometry = feature["geometry"]
        polygons = (
            [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        )
        # Anneau extérieur seulement, arrondi à 1e-4 degré (≈ 10 m) : la
        # précision suffit pour une région et divise la taille du fichier.
        rings = [[[round(x, 4), round(y, 4)] for x, y in polygon[0]] for polygon in polygons]
        shapes.append({"region": name, "rings": rings})
    return shapes


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    rows = read_tables(sys.argv[1])
    payload = {
        "source": "Référentiel donnebase de la base NetXMS de l'agence, "
                  "contours de frontend/public/regions-simplified.geojson",
        "generated_on": date.today().isoformat(),
        "cities": cities(rows),
        "regions": region_shapes(rows),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf8",
    )
    print(f"{OUTPUT.relative_to(ROOT)} : {len(payload['cities'])} villes, "
          f"{len(payload['regions'])} régions")


if __name__ == "__main__":
    main()
