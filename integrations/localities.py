"""
Province et région d'un équipement, sans accès à la base d'un outil.

Le connecteur NetXMS par la base lit le référentiel de l'agence directement
(integrations/netxms_db.py). Par l'API Web, ce référentiel n'est pas exposé :
seules la ville de l'objet et sa géolocalisation le sont. Ce module les
traduit à l'aide de `data/localities.json`, figé depuis le référentiel par
database/export_localities.py :

  1. la ville, si elle ne désigne qu'une seule province -> province et région ;
  2. sinon les coordonnées, placées dans le contour de leur région -> région
     seule (pas de contour de province dans le fichier).

Rien n'est deviné au-delà : une ville inconnue sans coordonnées reste sans
localité, et l'équipement est compté sous « Région non renseignée ».
"""
from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data" / "localities.json"


def _key(name: str) -> str:
    """Même clé que database/export_localities.py : majuscules, sans accents."""
    text = unicodedata.normalize("NFD", name or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.upper().replace("-", " ").replace("_", " ").split())


@lru_cache(maxsize=1)
def _referential() -> tuple[dict[str, list[str]], list[dict]]:
    payload = json.loads(_DATA.read_text(encoding="utf8"))
    return payload["cities"], payload["regions"]


def _inside(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Point dans un polygone, par lancer de rayon."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def region_at(latitude: float | None, longitude: float | None) -> str | None:
    if latitude is None or longitude is None:
        return None
    for shape in _referential()[1]:
        if any(_inside(longitude, latitude, ring) for ring in shape["rings"]):
            return shape["region"]
    return None


def locate(
    city: str | None, latitude: float | None = None, longitude: float | None = None
) -> tuple[str | None, str | None]:
    """(province, région) d'après la ville, puis d'après les coordonnées."""
    if city and city.strip():
        place = _referential()[0].get(_key(city))
        if place:
            return place[0], place[1]
    return None, region_at(latitude, longitude)
