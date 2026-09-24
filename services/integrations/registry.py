"""
Integration Registry — the catalog of every provider Forest AI knows about,
implemented or not. This is the single source of truth the Integrations
page and API read from; nothing else hardcodes a provider list.

`implemented=True` means a working adapter class exists (currently only the
three stage-1 demo adapters). Every other provider in this catalog is
listed with `implemented=False` and `status_claim="planned"` or
`"available"` — the UI must never render these as Connected, because no
adapter code exists to connect them yet.

`confirmed_customer_use` is deliberately conservative: only KRAUZERS (fleet/
telematics, exact vendor unconfirmed) and TIMBRO (forest audit — LiDAR/GNSS/
camera-based, in development) have a confirmed real-world tie mentioned in
project context. Every other provider (PONSSE, John Deere, Komatsu, ZF
SCALAR, LVM GEO, Planet/Maxar/ICEYE, generic ERP) is a catalog entry for a
*possible future* integration, not a claim that any current client uses it.
"""

from dataclasses import dataclass, field
from typing import Optional, Type

from .base import IntegrationAdapter


@dataclass
class ProviderEntry:
    provider: str                      # stable key, e.g. "ponsse_manager"
    category: str                      # machine | fleet | gis | satellite | timber | weighbridge | worker | erp | audit
    display_name: str
    vendor: str
    implemented: bool = False
    demo_available: bool = False
    adapter_class: Optional[Type[IntegrationAdapter]] = None
    status_claim: str = "planned"      # planned | available | demo | connected (connected only if implemented)
    confirmed_customer_use: Optional[str] = None   # None, or a short factual note
    notes: str = ""


def _catalog() -> list[ProviderEntry]:
    # Imported lazily inside the function (not at module import time) so
    # importing registry.py never fails if a demo adapter module has an
    # import-time error — the catalog listing itself must always work even
    # if one adapter is broken (test_connection/sync would just fail for
    # that one provider).
    from .demo.fleet_gps_demo import FleetGPSDemoAdapter
    from .demo.sentinel_demo import SentinelDemoAdapter
    from .demo.weighbridge_demo import WeighbridgeDemoAdapter

    return [
        # ── Machine telematics — all catalog-only in stage 1 ────────────
        ProviderEntry("ponsse_manager", "machine", "PONSSE Manager", "PONSSE",
                       status_claim="planned"),
        ProviderEntry("johndeere_timbermatic", "machine", "John Deere TimberMatic Maps", "John Deere",
                       status_claim="planned"),
        ProviderEntry("johndeere_timbermanager", "machine", "John Deere TimberManager", "John Deere",
                       status_claim="planned"),
        ProviderEntry("komatsu_smart_forestry", "machine", "Komatsu Smart Forestry", "Komatsu",
                       status_claim="planned"),
        ProviderEntry("komatsu_maxifleet", "machine", "Komatsu MaxiFleet", "Komatsu",
                       status_claim="planned"),
        ProviderEntry("komatsu_maxivision", "machine", "Komatsu MaxiVision", "Komatsu",
                       status_claim="planned"),

        # ── Fleet / GPS / logistics ──────────────────────────────────────
        ProviderEntry("zf_scalar", "fleet", "ZF SCALAR", "ZF", status_claim="planned"),
        ProviderEntry(
            "krauzers_fleet", "fleet", "KRAUZERS Fleet GPS", "KRAUZERS (exact vendor TBD",
            status_claim="planned",
            confirmed_customer_use=(
                "KRAUZERS is confirmed to use GPS/electronic fleet systems for timber trucks; "
                "the exact software vendor is not yet confirmed — do not name a specific product."
            ),
            notes="Do not mark Connected until the actual vendor/API is confirmed.",
        ),
        ProviderEntry("fleet_gps_demo", "fleet", "Fleet GPS (Demo)", "Forest AI demo",
                       implemented=True, demo_available=True, adapter_class=FleetGPSDemoAdapter,
                       status_claim="demo"),

        # ── GIS / maps ────────────────────────────────────────────────────
        ProviderEntry("lvm_geo", "gis", "LVM GEO", "LVM", status_claim="planned"),
        ProviderEntry("gis_generic", "gis", "Corporate GIS system", "generic", status_claim="planned"),
        ProviderEntry("geo_file_import", "gis", "GeoJSON / KML / GPX / Shapefile import", "generic",
                       status_claim="planned", notes="Stage 2."),

        # ── Satellite ─────────────────────────────────────────────────────
        ProviderEntry("sentinel_copernicus", "satellite", "Copernicus Sentinel-1/2", "ESA/Copernicus",
                       status_claim="available",
                       notes="Live token-check already exists via /api/satellite/token-check."),
        ProviderEntry("landsat", "satellite", "Landsat", "USGS/NASA", status_claim="planned"),
        ProviderEntry("planetscope", "satellite", "PlanetScope", "Planet", status_claim="planned"),
        ProviderEntry("skysat", "satellite", "SkySat", "Planet", status_claim="planned"),
        ProviderEntry("maxar", "satellite", "Maxar", "Maxar", status_claim="planned"),
        ProviderEntry("iceye", "satellite", "ICEYE", "ICEYE", status_claim="planned"),
        ProviderEntry("sentinel_demo", "satellite", "Sentinel (Demo)", "Forest AI demo",
                       implemented=True, demo_available=True, adapter_class=SentinelDemoAdapter,
                       status_claim="demo"),

        # ── Timber / weighbridge ─────────────────────────────────────────
        ProviderEntry("timber_accounting_generic", "timber", "Timber accounting / e-waybill system", "generic",
                       status_claim="planned", notes="Stage 2: CSV/API import into timber_movements."),
        ProviderEntry("weighbridge_generic", "weighbridge", "Weighbridge / scale system", "generic",
                       status_claim="planned", notes="Stage 2: CSV import."),
        ProviderEntry("weighbridge_demo", "weighbridge", "Weighbridge (Demo)", "Forest AI demo",
                       implemented=True, demo_available=True, adapter_class=WeighbridgeDemoAdapter,
                       status_claim="demo"),
        ProviderEntry("erp_generic", "erp", "Client ERP system", "generic", status_claim="planned"),

        # ── Workers / communication ───────────────────────────────────────
        ProviderEntry(
            "telegram_bot", "worker", "Telegram Bot", "Telegram", status_claim="available",
            notes="Already live in production via bot.py — this catalog entry documents it, "
                  "it is not managed through the generic adapter sync pipeline.",
        ),

        # ── Audit ─────────────────────────────────────────────────────────
        ProviderEntry(
            "timbro_audit", "audit", "TIMBRO Forest Audit", "TIMBRO", status_claim="planned",
            confirmed_customer_use=(
                "TIMBRO is confirmed to use or be developing a forest audit system "
                "(LiDAR + GNSS + camera photofixation + estimation algorithms). "
                "No API/data contract is confirmed yet — do not mark Connected."
            ),
        ),
    ]


_ADAPTER_CLASSES = None


def get_catalog() -> list[ProviderEntry]:
    return _catalog()


def get_provider_entry(provider: str) -> Optional[ProviderEntry]:
    for entry in _catalog():
        if entry.provider == provider:
            return entry
    return None


def get_adapter_class(provider: str) -> Optional[Type[IntegrationAdapter]]:
    entry = get_provider_entry(provider)
    return entry.adapter_class if entry and entry.implemented else None


def build_adapter(integration_row: dict) -> IntegrationAdapter:
    """Constructs the right adapter instance for a persisted integration
    row. Raises ValueError if the provider has no implemented adapter —
    callers (api.py routes) must turn that into a 4xx, never a 500."""
    adapter_cls = get_adapter_class(integration_row["provider"])
    if not adapter_cls:
        raise ValueError(
            f"Provider '{integration_row['provider']}' has no implemented adapter yet "
            "(catalog-only / planned integration)."
        )
    return adapter_cls(integration_row)
