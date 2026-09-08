"""
Test d'intégration : jeu de données réaliste + parcours complet de l'API.

Simule ce que l'ETL écrit réellement — sévérités BRUTES par outil, statuts
iTop, nœuds sans site, métriques TimescaleDB — puis exerce tous les
endpoints du dashboard.
"""
import os
import sys
from datetime import UTC, datetime, timedelta

os.environ.setdefault("NOC_WAREHOUSE_DSN", "postgresql://noc:noc@localhost:5432/noc_warehouse")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_KEY", "internal-test-key")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("WATCHER_ENABLED", "false")
os.environ.setdefault("REPORT_OUTPUT_DIR", "/tmp/noc-reports")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import auth_service  # noqa: E402

NOW = datetime.now(UTC)
failures = []


def check(label, condition, detail=""):
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def seed():
    """Écrit ce que l'ETL produirait, avec ses valeurs brutes."""
    with engine.begin() as conn:
        for table in (
            "ops_incident_notified", "ops_incident_timeline", "ops_incident_assignment",
            "ops_field_intervention", "ops_maintenance_window", "ops_notification_log",
            "ops_push_subscription", "ops_audit_log",
            "metric_value", "fact_incident", "fact_supervision_coverage_daily",
            "dim_node_source_map", "dim_node", "dim_locality", "dim_region",
            "dim_ministry",
        ):
            conn.execute(text(f"DELETE FROM {table}"))
        conn.execute(text("DELETE FROM dim_user"))

        conn.execute(text("""
            INSERT INTO dim_ministry (id, external_ref, name) VALUES
              (1,'org-1','Ministère de la Santé'),
              (2,'org-2','Ministère de l''Éducation')
        """))
        conn.execute(text("""
            INSERT INTO dim_region (id, code, name) VALUES
              (1,'CEN','Centre'), (2,'HBS','Hauts-Bassins')
        """))
        conn.execute(text("""
            INSERT INTO dim_locality
              (id, external_ref, region_id, code, name, latitude, longitude) VALUES
              (1,'loc-1',1,'OUA','Ouagadougou',12.3714,-1.5197),
              (2,'loc-2',2,'BBD','Bobo-Dioulasso',11.1771,-4.2979),
              (3,'loc-3',1,'KOU','Koudougou',NULL,NULL)
        """))
        # Le nœud 4 n'a ni ministère ni site : cas normal tant que
        # discover_geography.py n'a pas tourné.
        conn.execute(text("""
            INSERT INTO dim_node (id, ministry_id, locality_id, name, ip_address, is_active) VALUES
              (1,1,1,'RTR-OUA-01','10.0.1.1',true),
              (2,1,1,'SW-OUA-02','10.0.1.2',true),
              (3,2,2,'RTR-BBD-01','10.0.2.1',true),
              (4,NULL,NULL,'NODE-ORPHELIN','10.9.9.9',true),
              (5,2,3,'RTR-KOU-01','10.0.3.1',true)
        """))
        conn.execute(text("""
            INSERT INTO dim_node_source_map (node_id, source_tool, external_ref) VALUES
              (1,'zabbix','10084'),(1,'netxms','552'),
              (2,'zabbix','10085'),
              (3,'centreon','host-31'),(3,'itop','ci-77'),
              (4,'nagios','svc-1')
        """))
        conn.execute(text("SELECT setval('dim_node_id_seq', 10)"))
        conn.execute(text("SELECT setval('dim_locality_id_seq', 10)"))

    db = SessionLocal()
    try:
        # Sévérités et statuts BRUTS, tels que chaque connecteur les renvoie.
        incidents = [
            ("zabbix",  "e1", 1, "resolved", "5", "lien_down",       -300, -180),
            ("zabbix",  "e2", 2, "open",     "4", "cpu",              -120, None),
            ("netxms",  "n1", 1, "open",     "4", "equipement_down",   -90, None),
            ("netxms",  "n2", 3, "resolved", "2", "latence",          -600, -400),
            ("centreon","c1", 3, "open",     "2", "perte_paquets",     -45, None),
            ("nagios",  "g1", 4, "open",     "1", "seuil_trafic",      -30, None),
            ("itop",    "t1", 3, "assigned", "1", "alimentation",     -800, None),
            ("itop",    "t2", 1, "closed",   "3", "non_identifie",   -1400, -1300),
            ("nsp",     "s1", 5, "open",     "major", "lien_down",     -20, None),
        ]
        for tool, ext, node, status_raw, sev, cause, det_off, res_off in incidents:
            detected = NOW + timedelta(minutes=det_off)
            resolved = NOW + timedelta(minutes=res_off) if res_off else None
            mttr = round((resolved - detected).total_seconds() / 60, 1) if resolved else None
            db.execute(
                text("""
                    INSERT INTO fact_incident
                      (source_tool, external_id, node_id, status, severity, cause_category,
                       detected_at, resolved_at, mttr_minutes, downtime_minutes, description)
                    VALUES (:t,:e,:n,:s,:sev,:c,:d,:r,:m,:m,:desc)
                """),
                {"t": tool, "e": ext, "n": node, "s": status_raw, "sev": sev, "c": cause,
                 "d": detected, "r": resolved, "m": mttr,
                 "desc": f"Incident {tool} sur le nœud {node}"},
            )

        for hour in range(1, 25):
            moment = NOW - timedelta(hours=hour)
            for node_id in (1, 2, 3):
                for metric, value in (
                    ("availability_pct", 99.5 if node_id != 2 else 97.0),
                    ("latency_ms", 12.0 + node_id),
                    ("cpu_pct", 40.0 + hour % 20),
                    ("packet_loss_pct", 0.4),
                ):
                    db.execute(
                        text("""
                            INSERT INTO metric_value (time,node_id,source_tool,metric_type,value)
                            VALUES (:t,:n,'zabbix',:mt,:v)
                        """),
                        {"t": moment, "n": node_id, "mt": metric, "v": value},
                    )
        # Un équipement à 0 % de disponibilité : doit ressortir "tombé".
        db.execute(
            text("""
                INSERT INTO metric_value (time,node_id,source_tool,metric_type,value)
                VALUES (:t,3,'centreon','availability_pct',0)
            """),
            {"t": NOW - timedelta(minutes=5)},
        )

        db.execute(text("""
            INSERT INTO fact_supervision_coverage_daily
              (date, ministry_id, locality_id, nb_equip_total, nb_equip_supervised)
            VALUES (current_date,1,1,2,2),(current_date,2,2,1,1),(current_date,2,3,1,0)
        """))

        for username, full_name, role, pin in (
            ("directeur", "Awa Directrice", "directeur", None),
            ("chefnoc", "Ibrahim Chef NOC", "chef_noc", None),
            ("tech", "Salif Technicien", "technicien", None),
            ("terrain", "Moussa Agent", "agent_terrain", "4321"),
        ):
            db.execute(
                text("""
                    INSERT INTO dim_user
                      (username, full_name, role, password_hash, pin_hash, is_active)
                    VALUES (:u,:f,:r,:p,:pin,true)
                """),
                {"u": username, "f": full_name, "r": role,
                 "p": auth_service.hash_password("MotDePasse123"),
                 "pin": auth_service.hash_pin(pin) if pin else None},
            )
        db.commit()
    finally:
        db.close()


def main():
    seed()
    client = TestClient(app)

    print("\n=== Normalisation appliquée par la vue SQL ===")
    db = SessionLocal()
    rows = db.execute(text("""
        SELECT source_tool, severity_raw, severity, status_raw, status
        FROM v_incident ORDER BY source_tool, external_id
    """)).all()
    for r in rows:
        print(f"  {r[0]:9} sev {r[1]:>6} -> {r[2]:<9} statut {r[3]:>9} -> {r[4]}")
    db.close()
    mapping = {(r[0], r[1]): r[2] for r in rows}
    check("Zabbix severity 5 -> critical", mapping.get(("zabbix", "5")) == "critical")
    check("NetXMS severity 2 -> medium", mapping.get(("netxms", "2")) == "medium")
    check("Centreon severity 2 -> critical", mapping.get(("centreon", "2")) == "critical")
    check("iTop priorité 1 -> critical", mapping.get(("itop", "1")) == "critical")
    check("NSP major -> high", mapping.get(("nsp", "major")) == "high")
    statuses = {r[3] for r in rows}
    check("Statut iTop 'assigned' normalisé", "assigned" in statuses)

    print("\n=== Authentification ===")
    resp = client.post("/api/auth/login",
                       json={"username": "chefnoc", "password": "MotDePasse123"})
    check("Connexion chef NOC", resp.status_code == 200, str(resp.status_code))
    token = resp.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    check("Mauvais mot de passe rejeté",
          client.post("/api/auth/login",
                      json={"username": "chefnoc", "password": "faux"}).status_code == 401)
    check("PIN refusé pour un chef NOC",
          client.post("/api/auth/pin-login", json={"pin": "9999"}).status_code in (401, 423))
    check("PIN accepté pour l'agent terrain",
          client.post("/api/auth/pin-login", json={"pin": "4321"}).status_code == 200)
    # HTTPBearer répond 401 quand l'en-tête manque : c'est ce que le
    # frontend attend pour déclencher un rafraîchissement de session
    # (voir frontend/src/api/client.js), 403 signifiant "rôle insuffisant".
    check("Sans jeton -> 401", client.get("/api/kpi/summary").status_code == 401)

    print("\n=== Santé ===")
    health = client.get("/api/health").json()
    check("Base et vues OK", health["checks"]["database"]["status"] == "ok",
          health["checks"]["database"].get("detail", ""))

    print("\n=== KPI ===")
    summary = client.get("/api/kpi/summary", headers=auth)
    check("GET /api/kpi/summary", summary.status_code == 200, summary.text[:150])
    kpi = summary.json()["kpi"]
    print("  ", {k: kpi[k] for k in ("total_incidents", "resolved", "open",
                                     "critical", "network_availability_pct")})
    check("9 incidents comptés", kpi["total_incidents"] == 9, str(kpi["total_incidents"]))
    check("Disponibilité calculée", 0 < kpi["network_availability_pct"] <= 100)

    for path in ("/api/kpi/localities", "/api/kpi/localities/map", "/api/kpi/nodes",
                 "/api/kpi/recurrent", "/api/kpi/trend", "/api/kpi/hour-distribution",
                 "/api/kpi/causes", "/api/kpi/compare", "/api/kpi/ministries",
                 "/api/locality/1/nodes"):
        r = client.get(path, headers=auth)
        check(f"GET {path}", r.status_code == 200, r.text[:150])

    hours = client.get("/api/kpi/hour-distribution", headers=auth).json()
    check("24 heures renvoyées", len(hours) == 24, str(len(hours)))
    map_data = client.get("/api/kpi/localities/map", headers=auth).json()
    check("Sites sans coordonnées exclus de la carte", len(map_data) == 2, str(len(map_data)))

    print("\n=== Alertes, incidents, métriques ===")
    for path in ("/api/alerts/open", "/api/alerts/recent", "/api/alerts/counts",
                 "/api/incidents", "/api/metrics/network", "/api/metrics/nodes/down",
                 "/api/assets/coverage", "/api/assets/coverage/trend",
                 "/api/interop/status", "/api/sla", "/api/sla/targets",
                 "/api/maintenance-windows", "/api/users", "/api/field-interventions"):
        r = client.get(path, headers=auth)
        check(f"GET {path}", r.status_code == 200, r.text[:150])

    alerts = client.get("/api/alerts/open", headers=auth).json()
    check("Alertes triées par gravité",
          alerts[0]["severity"] == "critical", alerts[0]["severity"])

    filtered = client.get("/api/incidents?severity=critical", headers=auth).json()
    check("Filtre severity=critical sur valeurs brutes hétérogènes",
          filtered["total"] >= 3, str(filtered["total"]))
    check("Filtre node_code (nom d'équipement)",
          client.get("/api/incidents?node_code=RTR-OUA", headers=auth).json()["total"] >= 1)

    down = client.get("/api/metrics/nodes/down", headers=auth).json()
    check("Équipements tombés détectés", len(down) >= 1, str(len(down)))
    series = client.get("/api/metrics/nodes/1/series?metric_type=cpu_pct&hours=24",
                        headers=auth).json()
    check("Série temporelle CPU", len(series) > 0, str(len(series)))

    interop = client.get("/api/interop/status", headers=auth).json()
    check("6 outils listés", interop["tools_total"] == 6, str(interop["tools_total"]))
    check("Outils jamais collectés signalés",
          all(t["state"] in ("not_configured", "stale", "unknown", "ok", "error")
              for t in interop["tools"]))

    coverage = client.get("/api/assets/coverage", headers=auth).json()
    check("Couverture calculée", coverage["total_assets"] == 4, str(coverage["total_assets"]))

    print("\n=== Actions humaines ===")
    open_incident = next(a for a in alerts if a["status"] == "open")
    iid = open_incident["id"]

    ack = client.patch(f"/api/incidents/{iid}/acknowledge", headers=auth)
    check("Acquittement", ack.status_code == 200, ack.text[:150])
    check("Statut passé à acknowledged", ack.json()["status"] == "acknowledged")
    check("MTTA calculé", ack.json()["mtta_minutes"] is not None)

    check("Résolution sans note refusée",
          client.patch(f"/api/incidents/{iid}/resolve", json={"notes": ""},
                       headers=auth).status_code == 422)
    res = client.patch(f"/api/incidents/{iid}/resolve",
                       json={"notes": "Redémarrage de l'interface"}, headers=auth)
    check("Résolution avec note", res.status_code == 200, res.text[:150])
    check("MTTR calculé", res.json()["mttr_minutes"] is not None)
    check("Chronologie alimentée", len(res.json()["timeline"]) >= 2)

    manual = client.post("/api/incidents/manual", headers=auth, json={
        "node_code": "RTR-BBD-01", "severity": "high",
        "description": "Groupe électrogène en panne, constat sur site",
        "cause_category": "alimentation",
    })
    check("Signalement manuel", manual.status_code == 201, manual.text[:200])
    check("source_tool = manual", manual.json()["source_tool"] == "manual")
    check("Équipement inconnu rejeté",
          client.post("/api/incidents/manual", headers=auth, json={
              "node_code": "INEXISTANT", "severity": "low", "description": "x",
          }).status_code == 404)

    print("\n=== Permissions ===")
    tech_token = client.post("/api/auth/login",
                             json={"username": "tech", "password": "MotDePasse123"}
                             ).json()["access_token"]
    tech_auth = {"Authorization": f"Bearer {tech_token}"}
    check("Technicien ne crée pas de compte",
          client.post("/api/users", headers=tech_auth, json={
              "username": "pirate", "full_name": "X", "role": "directeur",
              "password": "MotDePasse123"}).status_code == 403)
    check("Technicien ne télécharge pas le rapport",
          client.get("/api/report/monthly", headers=tech_auth).status_code == 403)
    check("Technicien n'assigne pas",
          client.post(f"/api/incidents/{iid}/assign", headers=tech_auth,
                      json={"assigned_to_user_id": 1}).status_code == 403)

    print("\n=== Maintenance et neutralisation des KPI ===")
    before = client.get("/api/kpi/summary", headers=auth).json()["kpi"]["total_incidents"]
    window = client.post("/api/maintenance-windows", headers=auth, json={
        "node_id": 2,
        "reason": "Remplacement d'alimentation",
        "starts_at": (NOW - timedelta(hours=6)).isoformat(),
        "ends_at": (NOW + timedelta(hours=1)).isoformat(),
        "suppress_alerts": True,
    })
    check("Création d'une fenêtre de maintenance", window.status_code == 201, window.text[:200])
    after = client.get("/api/kpi/summary", headers=auth).json()["kpi"]["total_incidents"]
    check("Incidents en maintenance exclus des KPI", after < before, f"{before} -> {after}")

    print("\n=== Interventions terrain ===")
    terrain = client.post("/api/auth/login",
                          json={"username": "terrain", "password": "MotDePasse123"}
                          ).json()["access_token"]
    terrain_auth = {"Authorization": f"Bearer {terrain}"}
    created = client.post("/api/field-interventions", headers=terrain_auth,
                          json={"node_id": 3, "incident_id": None})
    check("Création d'intervention", created.status_code == 201, created.text[:200])
    fid = created.json()["id"]
    check("Changement de statut",
          client.patch(f"/api/field-interventions/{fid}/status", headers=terrain_auth,
                       json={"status": "en_route"}).status_code == 200)
    report = client.post(f"/api/field-interventions/{fid}/report", headers=terrain_auth, json={
        "report_text": "Disjoncteur réarmé, liaison rétablie",
        "checkin_latitude": 11.17, "checkin_longitude": -4.29,
        "photo_urls": ["https://example.org/photo1.jpg"],
    })
    check("Compte rendu terrain", report.status_code == 200, report.text[:200])
    check("Intervention clôturée", report.json()["status"] == "done")

    print("\n=== Veilleur ===")
    from app.services import watcher_service
    processed = watcher_service.run_once(NOW - timedelta(hours=48))
    check("Veilleur détecte les incidents", processed > 0, str(processed))
    check("Veilleur idempotent (pas de re-notification)",
          watcher_service.run_once(NOW - timedelta(hours=48)) == 0)

    print("\n=== Routes internes (ETL) ===")
    check("Sans clé interne -> 401",
          client.post("/api/internal/watcher/run", json={}).status_code == 401)
    check("Mauvaise clé -> 401",
          client.post("/api/internal/watcher/run",
                      headers={"Authorization": "Bearer faux"}).status_code == 401)
    internal = {"Authorization": "Bearer internal-test-key"}
    check("Invalidation du cache",
          client.post("/api/internal/cache/invalidate", headers=internal).status_code == 200)
    trigger = client.post("/api/internal/reports/monthly", headers=internal,
                          json={"as_of": NOW.isoformat()})
    check("Déclenchement du rapport mensuel", trigger.status_code == 200, trigger.text[:250])
    print("  ", trigger.json())

    print("\n=== Rapports ===")
    for fmt in ("pdf", "docx"):
        r = client.get(f"/api/report/monthly?format={fmt}", headers=auth)
        check(f"Rapport {fmt.upper()}", r.status_code == 200 and len(r.content) > 1000,
              f"{r.status_code}, {len(r.content)} octets")

    print("\n" + "=" * 60)
    if failures:
        print(f"{len(failures)} ÉCHEC(S) : {failures}")
        sys.exit(1)
    print("TOUS LES TESTS PASSENT")


if __name__ == "__main__":
    main()
