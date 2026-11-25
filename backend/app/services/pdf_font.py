"""
Police des rapports PDF.

Les polices intégrées de fpdf2 se limitent au latin-1 : « — », « → », « ≤ »,
« ’ » et « œ » y devenaient « ? » (A09). Liberation Sans, installée dans
l'image (backend/Dockerfile), les porte tous et a les mêmes largeurs
qu'Helvetica : la mise en page ne bouge pas.

Hors de l'image (poste de développement), repli sur Helvetica avec des
équivalents lisibles plutôt que des « ? ».
"""
from __future__ import annotations

import os

FONT_DIR = os.getenv("REPORT_FONT_DIR", "/usr/share/fonts/truetype/liberation")
_STYLES = {
    "": "LiberationSans-Regular.ttf", "B": "LiberationSans-Bold.ttf",
    "I": "LiberationSans-Italic.ttf",
}
_EQUIVALENTS = {
    "—": "-", "–": "-", "→": "->", "←": "<-", "≤": "<=", "≥": ">=", "’": "'", "‘": "'",
    "“": '"', "”": '"', "…": "...", "œ": "oe", "Œ": "Oe", " ": " ", "€": "EUR",
}


def setup(pdf):
    """(famille, conversion du texte) à utiliser pour ce document."""
    paths = {style: os.path.join(FONT_DIR, name) for style, name in _STYLES.items()}
    if all(os.path.isfile(path) for path in paths.values()):
        for style, path in paths.items():
            pdf.add_font("NOC", style, path)
        return "NOC", str

    def latin(value) -> str:
        text = str(value)
        for char, equivalent in _EQUIVALENTS.items():
            text = text.replace(char, equivalent)
        return text.encode("latin-1", "replace").decode("latin-1")

    return "Helvetica", latin
