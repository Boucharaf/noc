"""
Diagnostic d'un connecteur contre l'outil réel, sans rien publier.

    docker compose run --rm collector python -m collector.probe            # tous
    docker compose run --rm collector python -m collector.probe netxms     # un seul
    docker compose run --rm -v "$PWD:/out" collector \\
        python -m collector.probe netxms nsp --json /out/recette.json      # rapport

POURQUOI. En production, toutes les données viennent des API des outils. Un
connecteur qui n'a jamais rencontré l'instance de l'agence (NetXMS par son
API, Nokia NSP) peut lire des réponses de forme inattendue sans échouer : des
équipements sans localité, des alertes sans équipement. Ce diagnostic fait un
cycle de lecture, sans Redis ni base, et dit ce qui est lu et ce qui manque.
La procédure de recette est au chapitre 9 de la documentation.

Il n'affiche aucune valeur sensible : des comptes, des taux de remplissage, et
pour NetXMS les NOMS des champs renvoyés par l'API (pas leurs valeurs), pour
confronter le connecteur à la forme réelle des réponses. Le rapport JSON a le
même contenu : il peut être transmis tel quel.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from datetime import datetime, timezone

from integrations.base import ToolUnavailable
from integrations.config import TOOL_NAMES, build_client, configured_tools

_NODE_FIELDS = (
    ("ip", "adresse IP"), ("site", "site"), ("province", "province"),
    ("region", "région"), ("latitude", "coordonnées"),
)
_FACTS = (
    ("inventory", "inventaire"), ("interfaces", "interfaces"), ("links", "liens surveillés"),
    ("availability", "dispo. agence"), ("boot_time", "démarrage"),
)


def _pct(count: int, total: int) -> str:
    return f"{count}/{total} ({100 * count / total:.0f} %)" if total else "0"


async def _netxms_fields(client) -> dict:
    """Noms des champs d'un équipement et d'une alarme, tels que l'API les rend."""
    if not hasattr(client, "_list_objects"):
        return {}  # accès par la base : pas de réponse JSON à inspecter
    fields: dict = {}
    try:
        body = await client._get("/objects", {"class": "Node", "offset": 0, "limit": 1})
        objects = body.get("objects", []) if isinstance(body, dict) else body
        if objects:
            fields["node"] = sorted(objects[0])
        body = await client._get("/alarms")
        alarms = body.get("alarms", []) if isinstance(body, dict) else body
        if alarms:
            fields["alarm"] = sorted(alarms[0])
    except ToolUnavailable as exc:
        fields["error"] = str(exc)
    return fields


async def inspect(name: str) -> dict:
    """Rapport d'un outil : santé, couverture de l'inventaire et des alertes."""
    client = build_client(name)
    if client is None:
        return {"tool": name, "configured": False}
    report: dict = {"tool": name, "configured": True, "connector": type(client).__name__}
    try:
        health = await client.check()
        report.update(reachable=health.reachable, version=health.version,
                      latency_ms=round(health.latency_ms or 0), error=health.error)
        if not health.reachable:
            return report

        nodes = await client.fetch_nodes()
        total = len(nodes)
        report["nodes"] = {
            "total": total,
            "filled": {key: sum(1 for n in nodes if getattr(n, key)) for key, _ in _NODE_FIELDS},
            "facts": {
                key: sum(1 for n in nodes if (n.details or {}).get(key)) for key, _ in _FACTS
            },
            "links": sum(len((n.details or {}).get("links") or []) for n in nodes),
            "states": dict(collections.Counter(n.state for n in nodes).most_common()),
        }

        alerts = await client.fetch_alerts()
        refs = {node.ref for node in nodes}
        report["alerts"] = {
            "total": len(alerts),
            "attached": sum(1 for alert in alerts if alert.node_ref in refs),
            "severities": dict(collections.Counter(a.severity for a in alerts)),
        }
        if name == "netxms":
            report["fields"] = await _netxms_fields(client)
    except ToolUnavailable as exc:
        report.update(reachable=False, error=str(exc))
    finally:
        await client.aclose()
    return report


def _print(report: dict) -> None:
    name = report["tool"]
    if not report.get("configured"):
        print(f"\n{name} : non configuré ({name.upper()}_API_URL vide)")
        return
    print(f"\n{name} : {report['connector']}")
    if not report.get("reachable"):
        print(f"  INJOIGNABLE : {report.get('error')}")
        return
    print(f"  joignable en {report['latency_ms']} ms, version {report.get('version') or '?'}")
    nodes = report.get("nodes")
    if nodes is None:
        print(f"  ÉCHEC : {report.get('error')}")
        return
    total = nodes["total"]
    print(f"  équipements : {total}")
    if total:
        for key, label in _NODE_FIELDS:
            print(f"    {label:16s} {_pct(nodes['filled'][key], total)}")
        facts = [(label, nodes["facts"][key]) for key, label in _FACTS if nodes["facts"][key]]
        for label, count in facts:
            print(f"    {label:16s} {_pct(count, total)}")
        if nodes["links"]:
            print(f"    {'liens suivis':16s} {nodes['links']}")
        print(f"    {'états':16s} {nodes['states']}")
    alerts = report.get("alerts")
    if alerts is None:
        print(f"  ÉCHEC : {report.get('error')}")
        return
    print(f"  alertes actives : {alerts['total']}")
    if alerts["total"]:
        print(f"    {'rattachées':16s} {_pct(alerts['attached'], alerts['total'])}")
        print(f"    {'gravités':16s} {alerts['severities']}")
    for kind, names in (report.get("fields") or {}).items():
        print(f"  champs {kind:8s} : {names if isinstance(names, str) else ', '.join(names)}")


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m collector.probe")
    parser.add_argument("tools", nargs="*", help=f"parmi : {', '.join(TOOL_NAMES)}")
    parser.add_argument("--json", dest="json_path", help="écrire aussi le rapport en JSON")
    args = parser.parse_args(argv)

    unknown = [name for name in args.tools if name not in TOOL_NAMES]
    if unknown:
        print(f"Outil(s) inconnu(s) : {', '.join(unknown)} — attendus : {', '.join(TOOL_NAMES)}")
        return 2
    reports = []
    for name in args.tools or configured_tools():
        report = await inspect(name)
        _print(report)
        reports.append(report)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf8") as handle:
            json.dump(
                {"generated_at": datetime.now(timezone.utc).isoformat(), "tools": reports},
                handle, ensure_ascii=False, indent=2, default=str,
            )
        print(f"\nRapport écrit : {args.json_path}")
    ok = all(r.get("reachable") and "alerts" in r for r in reports if r.get("configured"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
