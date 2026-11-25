"""
Identité stable des équipements.

POURQUOI. La fusion (collector/merge.py) nomme chaque équipement d'après le
premier outil qui le voit (« netxms:7 »). Retirer cet outil, en ajouter un
autre ou recréer l'hôte changeait ce nom, et l'historique se coupait en deux.
Ici, un REGISTRE (noc_asset, noc_asset_source) retient à quel équipement
appartient chaque référence d'outil : l'identifiant est donné une fois et ne
change plus.

L'identifiant d'un nouvel équipement reste celui de la fusion : l'historique
existant est repris tel quel, sans réécriture. Il est ensuite OPAQUE :
« netxms:7 » reste l'identifiant même quand NetXMS ne voit plus l'équipement.

RÈGLES, de la plus sûre à la moins sûre :
  1. une référence déjà connue garde son équipement (renommage OU changement
     d'adresse compris) ;
  2. si le nom ET l'adresse ont changé ensemble, la référence a
     vraisemblablement été réattribuée : nouvel équipement ;
  3. une référence inconnue de mêmes nom ET adresse qu'un équipement disparu
     le reprend (hôte recréé, outil remplacé), seulement si c'est le seul
     candidat et si les outils qui le voyaient ont bien répondu sans lui ;
  4. deux équipements que la fusion réunit : le plus ancien continue, l'autre
     est marqué `merged_into`. Son historique passé reste sous son
     identifiant : les additionner compterait deux fois le même temps ;
  5. un équipement que la fusion sépare : une part garde l'identifiant,
     l'autre en reçoit un (le sien, si elle en avait un avant la réunion).

Dans le doute : un nouvel équipement. Une coupure se répare (`attach`
ci-dessous) ; deux équipements confondus faussent les chiffres des deux.

Chaque décision est tracée dans noc_asset_event.

    python -m collector.identity show <identifiant>
    python -m collector.identity events [--days 7]
    python -m collector.identity lost [--days 1]
    python -m collector.identity attach <outil:ref> <identifiant>
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import config
from .merge import _normalise_name, _valid_ip

logger = logging.getLogger(__name__)


@dataclass
class Binding:
    """À quel équipement appartient une référence d'outil, et sous quels nom
    et adresse elle a été vue."""

    asset_id: str
    name: str = ""
    ip: str | None = None


@dataclass
class Asset:
    created_at: datetime
    merged_into: str | None = None
    name: str | None = None


@dataclass
class Registry:
    assets: dict[str, Asset] = field(default_factory=dict)
    bindings: dict[str, Binding] = field(default_factory=dict)   # « outil:ref »

    def final(self, asset_id: str) -> str:
        """L'équipement qui continue, en suivant les réunions."""
        seen = set()
        while asset_id not in seen:
            seen.add(asset_id)
            target = self.assets[asset_id].merged_into if asset_id in self.assets else None
            if not target:
                break
            asset_id = target
        return asset_id


@dataclass
class Plan:
    ids: dict[str, str] = field(default_factory=dict)        # id de fusion -> id stable
    assets: dict[str, str | None] = field(default_factory=dict)   # id -> nom (à créer)
    merged: dict[str, str | None] = field(default_factory=dict)   # id -> merged_into
    bindings: dict[str, Binding] = field(default_factory=dict)
    recycled: set[str] = field(default_factory=set)
    moved: bool = False      # des références ont changé d'équipement
    events: list[dict] = field(default_factory=list)

    def event(self, asset_id: str, event: str, source: str | None = None,
              from_value: str | None = None, to_value: str | None = None) -> None:
        self.events.append({"asset_id": asset_id, "event": event, "source": source,
                            "from_value": from_value, "to_value": to_value})


_cache: Registry | None = None


def _keys(node) -> list[str]:
    return [f"{tool}:{ref}" for tool, ref in sorted(node.sources.items())]


def _same_equipment(binding: Binding, name: str, ip: str | None) -> bool:
    """Faux seulement si nom ET adresse, tous connus, ont changé ensemble."""
    renamed = bool(binding.name and name and binding.name != name)
    moved = bool(binding.ip and ip and binding.ip != ip)
    return not (renamed and moved)


def resolve(merged, registry: Registry, answered: set[str], known: set[str],
            now: datetime) -> Plan:
    """Identifiant stable de chaque équipement fusionné.

    `answered` : outils dont l'inventaire vient d'être lu ; `known` : outils
    configurés. Pure (aucun accès base) ; met `registry` à jour en mémoire.
    """
    plan = Plan()
    nodes = sorted(merged, key=lambda n: n.id)
    identity = {n.id: (_normalise_name(n.hostname or n.name), _valid_ip(n.ip)) for n in nodes}
    present = {key for n in nodes for key in _keys(n)}

    # 1 et 2 — références connues.
    claims: dict[str, list] = defaultdict(list)
    wanted: dict[str, set[str]] = {}
    for node in nodes:
        wanted[node.id] = set()
        for key in _keys(node):
            binding = registry.bindings.get(key)
            if binding is None:
                continue
            if not _same_equipment(binding, *identity[node.id]):
                plan.recycled.add(key)
                continue
            asset_id = registry.final(binding.asset_id)
            if asset_id not in wanted[node.id]:
                wanted[node.id].add(asset_id)
                claims[asset_id].append(node)

    taken: set[str] = set()

    def assign(node, asset_id: str) -> None:
        plan.ids[node.id] = asset_id
        taken.add(asset_id)

    # 5 — un équipement réclamé par plusieurs : à celui qui porte la référence
    # d'origine, sinon à celui qui a le plus de sources.
    for asset_id in sorted(claims, key=lambda a: (registry.assets[a].created_at, a)):
        claimants = [n for n in claims[asset_id] if n.id not in plan.ids]
        if claimants:
            assign(min(claimants, key=lambda n: (
                asset_id not in _keys(n), -len(n.sources), n.id
            )), asset_id)

    # 3 — hôte recréé, outil remplacé.
    same_now: dict[tuple, int] = defaultdict(int)
    for pair in identity.values():
        same_now[pair] += 1
    lost = _lost_assets(registry, taken, present, answered, known)
    for node in nodes:
        pair = identity[node.id]
        if node.id in plan.ids or wanted[node.id] or not all(pair) or same_now[pair] > 1:
            continue
        found = [asset_id for asset_id in lost.get(pair, ()) if asset_id not in taken]
        if len(found) == 1:
            assign(node, found[0])
            plan.event(found[0], "rebound", _keys(node)[0])

    # Sinon : nouvel équipement.
    for node in nodes:
        if node.id in plan.ids:
            continue
        recycled = any(key in plan.recycled for key in _keys(node))
        asset_id, existing = node.id, registry.assets.get(node.id)
        if existing is not None and existing.merged_into and node.id not in taken and not recycled:
            existing.merged_into = None
            plan.merged[asset_id] = None
            plan.event(asset_id, "separated")
        else:
            suffix = 2
            while asset_id in registry.assets or asset_id in taken:
                asset_id = f"{node.id}~{suffix}"
                suffix += 1
            registry.assets[asset_id] = Asset(now, name=node.name)
            plan.assets[asset_id] = node.name
            plan.event(asset_id, "created", _keys(node)[0])
        assign(node, asset_id)

    # 4 — réunion : l'autre équipement n'a plus aucune source ailleurs.
    owner = {key: plan.ids[n.id] for n in nodes for key in _keys(n)}
    for node in nodes:
        for other in sorted(wanted[node.id] - {plan.ids[node.id]}):
            elsewhere = any(
                registry.final(b.asset_id) == other and key in present
                and owner[key] != plan.ids[node.id]
                for key, b in registry.bindings.items()
            )
            if other in taken or elsewhere:
                continue
            registry.assets[other].merged_into = plan.ids[node.id]
            plan.merged[other] = plan.ids[node.id]
            plan.event(other, "merged", to_value=plan.ids[node.id])

    # Références : créées, déplacées ou renommées.
    for node in nodes:
        name, ip = identity[node.id]
        asset_id = plan.ids[node.id]
        for key in _keys(node):
            old = registry.bindings.get(key)
            new = Binding(asset_id, name or (old.name if old else ""),
                          ip or (old.ip if old else None))
            if old == new:
                continue
            if old is None:
                plan.moved = True
                if asset_id not in plan.assets:
                    plan.event(asset_id, "source_added", key)
            elif old.asset_id != asset_id:
                plan.moved = True
                plan.event(asset_id, "source_recycled" if key in plan.recycled
                           else "source_moved", key, old.asset_id, asset_id)
            else:
                plan.event(asset_id, "renamed", key, f"{old.name} {old.ip or ''}".strip(),
                           f"{new.name} {new.ip or ''}".strip())
            plan.bindings[key] = new
    registry.bindings.update(plan.bindings)
    return plan


def _lost_assets(registry: Registry, taken: set[str], present: set[str],
                 answered: set[str], known: set[str]) -> dict[tuple, list[str]]:
    """Équipements dont TOUTES les références ont disparu, avec certitude,
    par (nom, adresse). Un outil muet ne prouve aucune disparition."""
    by_asset: dict[str, list[tuple[str, Binding]]] = defaultdict(list)
    for key, binding in registry.bindings.items():
        by_asset[registry.final(binding.asset_id)].append((key, binding))
    lost: dict[tuple, list[str]] = defaultdict(list)
    for asset_id, items in by_asset.items():
        if asset_id in taken:
            continue
        if any(
            key in present
            or (key.partition(":")[0] in known and key.partition(":")[0] not in answered)
            for key, _binding in items
        ):
            continue
        for pair in {(b.name, b.ip) for _key, b in items if b.name and b.ip}:
            lost[pair].append(asset_id)
    return lost


def rename(merged, report, ids: dict[str, str]) -> None:
    """Pose les identifiants stables sur le parc et sur le rapport de fusion."""
    for item in (*report.single_source, *report.state_conflicts):
        item["id"] = ids.get(item["id"], item["id"])
    for node in merged:
        node.id = ids.get(node.id, node.id)


def tools_status(source_status: dict) -> tuple[set[str], set[str]]:
    """(outils dont l'inventaire vient d'être lu, outils configurés)."""
    answered = {
        tool for tool, streams in (source_status or {}).items()
        if (stream := (streams or {}).get("nodes") or {}).get("collected_at")
        and not stream.get("stale")
    }
    return answered, set(source_status or {})


async def apply(merged, report, source_status: dict, now: datetime) -> bool:
    """Pose les identifiants stables. Ne lève jamais.

    Rend False quand ils n'ont pas pu l'être : l'appelant n'écrit alors pas
    d'historique à ce cycle, plutôt que de l'écrire sous un identifiant faux.
    """
    global _cache
    answered, known = tools_status(source_status)
    try:
        plan, registry = await asyncio.wait_for(
            _resolve_and_store(merged, answered, known, now), timeout=config.IDENTITY_TIMEOUT_S
        )
        _cache = registry
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ == "UndefinedTable":
            # Schéma pas encore mis à jour : comportement antérieur. Ces
            # identifiants sont ceux que le registre reprendra.
            logger.warning("Registre d'identité absent : rejouer backend/sql/schema.sql")
            return True
        logger.exception("Registre d'identité non lu")
        if _cache is None:
            return False
        plan = resolve(merged, _cache, answered, known, now)
    rename(merged, report, plan.ids)
    for event in plan.events:
        if event["event"] not in ("created", "source_added"):
            logger.info("Identité : %s", event)
    return True


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
async def load(cur) -> Registry:
    await cur.execute("SELECT id, created_at, merged_into, name FROM noc_asset")
    assets = {
        row["id"]: Asset(row["created_at"], row["merged_into"], row["name"])
        for row in await cur.fetchall()
    }
    await cur.execute("SELECT tool, ref, asset_id, name, ip FROM noc_asset_source")
    bindings = {
        f"{row['tool']}:{row['ref']}": Binding(row["asset_id"], row["name"] or "", row["ip"])
        for row in await cur.fetchall()
    }
    return Registry(assets, bindings)


async def _connect():
    import psycopg
    from psycopg.rows import dict_row

    return await psycopg.AsyncConnection.connect(
        config.DATABASE_URL, row_factory=dict_row, connect_timeout=10
    )


async def _resolve_and_store(merged, answered, known, now) -> tuple[Plan, Registry]:
    async with await _connect() as conn:
        async with conn.cursor() as cur:
            registry = await load(cur)
            plan = resolve(merged, registry, answered, known, now)
            await store(cur, plan, merged, registry, now)
        await conn.commit()
    return plan, registry


async def store(cur, plan: Plan, merged, registry: Registry, now: datetime) -> None:
    if plan.assets:
        # Reprise d'un historique existant : l'équipement est aussi ancien
        # que sa première période.
        await cur.executemany(
            "INSERT INTO noc_asset (id, name, created_at, last_seen_at) VALUES (%(id)s, "
            "%(name)s, COALESCE((SELECT min(started_at) FROM hist_state "
            "WHERE node_id = %(id)s), %(now)s), %(now)s)",
            [{"id": i, "name": name, "now": now} for i, name in plan.assets.items()],
        )
    if plan.merged:
        await cur.executemany(
            "UPDATE noc_asset SET merged_into = %s WHERE id = %s",
            [(target, i) for i, target in plan.merged.items()],
        )
    if plan.bindings:
        await cur.executemany(
            """
            INSERT INTO noc_asset_source (tool, ref, asset_id, name, ip, first_seen_at)
            VALUES (%(tool)s, %(ref)s, %(asset_id)s, %(name)s, %(ip)s, %(now)s)
            ON CONFLICT (tool, ref) DO UPDATE SET
                asset_id = EXCLUDED.asset_id, name = EXCLUDED.name, ip = EXCLUDED.ip,
                valid_from = CASE WHEN %(recycled)s THEN %(now)s::timestamptz
                             ELSE noc_asset_source.valid_from END
            """,
            [
                {
                    "tool": key.partition(":")[0], "ref": key.partition(":")[2],
                    "asset_id": b.asset_id, "name": b.name, "ip": b.ip, "now": now,
                    "recycled": key in plan.recycled,
                }
                for key, b in plan.bindings.items()
            ],
        )
    if plan.moved:
        # Les pannes copiées suivent l'objet de l'outil, pas l'ancien
        # identifiant. Référence réattribuée : le passé reste à l'ancien.
        await cur.execute(
            "UPDATE hist_downtime d SET node_id = s.asset_id FROM noc_asset_source s "
            "WHERE s.tool = d.source AND s.ref = d.object_ref AND d.node_id <> s.asset_id "
            "AND d.started_at >= COALESCE(s.valid_from, '-infinity')"
        )
        await cur.execute(
            "UPDATE hist_source_object o SET node_id = s.asset_id FROM noc_asset_source s "
            "WHERE s.tool = o.source AND s.ref = o.object_ref AND o.node_id <> s.asset_id"
        )
    if plan.events:
        await cur.executemany(
            "INSERT INTO noc_asset_event (asset_id, event, at, source, from_value, to_value) "
            "VALUES (%(asset_id)s, %(event)s, %(at)s, %(source)s, %(from_value)s, %(to_value)s)",
            [{**event, "at": now} for event in plan.events],
        )
    names = [
        (node.name, asset_id) for node in merged
        if registry.assets[asset_id := plan.ids[node.id]].name != node.name
    ]
    if names:
        await cur.executemany("UPDATE noc_asset SET name = %s WHERE id = %s", names)
    await cur.execute(
        "UPDATE noc_asset SET last_seen_at = %s WHERE id = ANY(%s)",
        (now, list(plan.ids.values())),
    )


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------
async def attach(source: str, asset_id: str, now: datetime) -> str:
    """Rattache une référence à un équipement DISPARU, pour reprendre son
    historique. Rend le message à afficher ; lève ValueError si refusé."""
    async with await _connect() as conn:
        async with conn.cursor() as cur:
            registry = await load(cur)
            binding, asset = registry.bindings.get(source), registry.assets.get(asset_id)
            if binding is None:
                raise ValueError(f"référence inconnue : {source}")
            if asset is None:
                raise ValueError(f"équipement inconnu : {asset_id}")
            previous = binding.asset_id
            if asset.merged_into or previous == asset_id:
                raise ValueError(f"{asset_id} est déjà réuni ou déjà rattaché")
            await cur.execute("SELECT last_seen_at FROM noc_asset WHERE id = %s", (asset_id,))
            seen = (await cur.fetchone())["last_seen_at"]
            if now - seen <= timedelta(seconds=config.OBSERVATION_GAP_S):
                # Deux équipements vus en même temps : la fusion les
                # séparerait au cycle suivant.
                raise ValueError(
                    f"{asset_id} est encore vu : aligner nom et adresse dans les outils"
                )
            siblings = [k for k, b in registry.bindings.items() if b.asset_id == previous]
            if siblings != [source]:
                raise ValueError(f"{previous} a d'autres références : {', '.join(siblings)}")
            await cur.execute(
                "UPDATE noc_asset_source SET asset_id = %s WHERE tool = %s AND ref = %s",
                (asset_id, *source.split(":", 1)),
            )
            await cur.execute(
                "UPDATE noc_asset SET merged_into = %s WHERE id = %s", (asset_id, previous)
            )
            await cur.execute(
                "UPDATE hist_downtime SET node_id = %s WHERE source = %s AND object_ref = %s "
                "AND node_id = %s", (asset_id, *source.split(":", 1), previous),
            )
            await cur.execute(
                "UPDATE hist_source_object SET node_id = %s WHERE source = %s "
                "AND object_ref = %s", (asset_id, *source.split(":", 1)),
            )
            await cur.execute(
                "INSERT INTO noc_asset_event (asset_id, event, at, source, from_value, to_value) "
                "VALUES (%s, 'attached', %s, %s, %s, %s)",
                (asset_id, now, source, previous, asset_id),
            )
        await conn.commit()
    return f"{source} : {previous} -> {asset_id} (effectif au prochain cycle)"


async def _main(args) -> None:
    now = datetime.now(timezone.utc)
    if args.command == "attach":
        try:
            print(await attach(args.source, args.asset, now))
        except ValueError as exc:
            raise SystemExit(f"Refusé : {exc}") from exc
        return
    queries = {
        "show": (
            "SELECT tool || ':' || ref AS ligne, name, ip, first_seen_at AS at "
            "FROM noc_asset_source WHERE asset_id = %(id)s UNION ALL "
            "SELECT event, COALESCE(source, ''), concat_ws(' -> ', from_value, to_value), at "
            "FROM noc_asset_event WHERE asset_id = %(id)s ORDER BY at"
        ),
        "events": (
            "SELECT at, asset_id, event, source, from_value, to_value FROM noc_asset_event "
            "WHERE at >= %(since)s AND event <> 'created' ORDER BY at"
        ),
        "lost": (
            "SELECT id, name, last_seen_at FROM noc_asset "
            "WHERE merged_into IS NULL AND last_seen_at < %(since)s ORDER BY last_seen_at DESC"
        ),
    }
    async with await _connect() as conn:
        async with conn.cursor() as cur:
            await cur.execute(queries[args.command], {
                "id": getattr(args, "asset", None),
                "since": now - timedelta(days=getattr(args, "days", 0)),
            })
            for row in await cur.fetchall():
                print(" | ".join("" if v is None else str(v) for v in row.values()))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m collector.identity")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show").add_argument("asset")
    commands.add_parser("events").add_argument("--days", type=int, default=7)
    commands.add_parser("lost").add_argument("--days", type=int, default=1)
    link = commands.add_parser("attach")
    link.add_argument("source")
    link.add_argument("asset")
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
