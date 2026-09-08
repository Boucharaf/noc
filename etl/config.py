"""
Configuration centrale de l'ETL NOC.

Toutes les valeurs viennent de variables d'environnement (voir .env.example
à la racine du projet). Rien n'est codé en dur ici : un outil absent ou mal
configuré désactive simplement son connecteur au démarrage (voir
pipelines/status.py), il ne fait jamais planter tout le pipeline.
"""
import os
from dataclasses import dataclass, field
from typing import Optional


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Entrepôt cible (PostgreSQL + TimescaleDB)
# ---------------------------------------------------------------------------
@dataclass
class WarehouseConfig:
    dsn: str = os.getenv(
        "NOC_WAREHOUSE_DSN",
        "postgresql://noc:noc@localhost:5432/noc_warehouse",
    )


# ---------------------------------------------------------------------------
# Un bloc de config par outil : API (obligatoire) + BDD restaurée (optionnelle)
# ---------------------------------------------------------------------------
@dataclass
class ToolConfig:
    name: str
    api_enabled: bool
    api_base_url: Optional[str] = None
    api_user: Optional[str] = None
    api_password: Optional[str] = None
    api_token: Optional[str] = None
    verify_ssl: bool = True

    # BDD restaurée (pg_dump) — jamais requise, uniquement en complément
    db_restore_enabled: bool = False
    db_dsn: Optional[str] = None  # DSN PostgreSQL du schéma de staging restauré


def _tool(prefix: str) -> ToolConfig:
    return ToolConfig(
        name=prefix.lower(),
        api_enabled=_bool(f"{prefix}_API_ENABLED", True),
        api_base_url=os.getenv(f"{prefix}_API_URL"),
        api_user=os.getenv(f"{prefix}_API_USER"),
        api_password=os.getenv(f"{prefix}_API_PASSWORD"),
        api_token=os.getenv(f"{prefix}_API_TOKEN"),
        verify_ssl=_bool(f"{prefix}_VERIFY_SSL", True),
        db_restore_enabled=_bool(f"{prefix}_DB_RESTORE_ENABLED", False),
        db_dsn=os.getenv(f"{prefix}_DB_DSN"),
    )


@dataclass
class Settings:
    warehouse: WarehouseConfig = field(default_factory=WarehouseConfig)

    zabbix: ToolConfig = field(default_factory=lambda: _tool("ZABBIX"))
    itop: ToolConfig = field(default_factory=lambda: _tool("ITOP"))
    netxms: ToolConfig = field(default_factory=lambda: _tool("NETXMS"))
    centreon: ToolConfig = field(default_factory=lambda: _tool("CENTREON"))

    # Nagios et NSP : connecteurs créés mais en attente de confirmation sur
    # la variante réellement disponible côté agence (voir README extract/api).
    nagios: ToolConfig = field(default_factory=lambda: _tool("NAGIOS"))
    nagios_mode: str = os.getenv("NAGIOS_MODE", "unknown")  # livestatus | xi | ndoutils | unknown
    nsp: ToolConfig = field(default_factory=lambda: _tool("NSP"))
    nsp_fm_mode: str = os.getenv("NSP_FM_MODE", "unknown")  # classic | yang | unknown

    # Intervalle de collecte (secondes)
    collect_interval_s: int = int(os.getenv("COLLECT_INTERVAL_S", "300"))


settings = Settings()
