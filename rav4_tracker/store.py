"""SQLite persistence for vehicles previously seen by the tracker."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import config


VEHICLE_COLUMNS = """
    vin TEXT PRIMARY KEY,
    stock_num TEXT,
    brand TEXT,
    marketing_series TEXT,
    year INTEGER,
    dealer_cd TEXT,
    dealer_marketing_name TEXT,
    dealer_website TEXT,
    vdp_url TEXT,
    distance REAL,
    inventory_status TEXT,
    is_pre_sold INTEGER,
    total_msrp INTEGER,
    advertized_price INTEGER,
    base_msrp INTEGER,
    dph INTEGER,
    model_cd TEXT,
    model_marketing_name TEXT,
    model_marketing_title TEXT,
    int_color_cd TEXT,
    int_color_name TEXT,
    ext_color_cd TEXT,
    ext_color_name TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
"""


def connect_db() -> sqlite3.Connection:
    path = Path(config.VEHICLE_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def create_vehicles_table(connection: sqlite3.Connection) -> None:
    connection.execute(f"CREATE TABLE IF NOT EXISTS vehicles ({VEHICLE_COLUMNS})")


def create_vehicle_summary_view(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP VIEW IF EXISTS vehicle_summary;
        CREATE VIEW vehicle_summary AS
        SELECT
            vin,
            model_marketing_title AS model,
            ext_color_name AS exterior,
            int_color_name AS interior,
            total_msrp,
            dealer_marketing_name AS dealer,
            distance,
            inventory_status AS status,
            first_seen_at,
            last_seen_at
        FROM vehicles
        ORDER BY last_seen_at DESC, vin;
        """
    )


def migrate_vehicles_table_without_payload(connection: sqlite3.Connection) -> None:
    """Remove legacy raw payload storage while preserving vehicle history."""
    connection.executescript(
        f"""
        DROP VIEW IF EXISTS vehicle_summary;
        ALTER TABLE vehicles RENAME TO vehicles_old;
        CREATE TABLE vehicles ({VEHICLE_COLUMNS});
        INSERT INTO vehicles (
            vin, stock_num, brand, marketing_series, year, dealer_cd,
            dealer_marketing_name, dealer_website, vdp_url, distance,
            inventory_status, is_pre_sold, total_msrp, advertized_price,
            base_msrp, dph, model_cd, model_marketing_name,
            model_marketing_title, int_color_cd, int_color_name,
            ext_color_cd, ext_color_name, first_seen_at, last_seen_at
        )
        SELECT
            vin, stock_num, brand, marketing_series, year, dealer_cd,
            dealer_marketing_name, dealer_website, vdp_url, distance,
            inventory_status, is_pre_sold, total_msrp, advertized_price,
            base_msrp, dph, model_cd, model_marketing_name,
            model_marketing_title, int_color_cd, int_color_name,
            ext_color_cd, ext_color_name, first_seen_at, last_seen_at
        FROM vehicles_old
        WHERE last_payload IS NOT NULL AND last_payload != '{{}}';
        DROP TABLE vehicles_old;
        DROP TABLE IF EXISTS vehicle_payloads;
        """
    )


def init_db(connection: sqlite3.Connection) -> None:
    if "last_payload" in table_columns(connection, "vehicles"):
        migrate_vehicles_table_without_payload(connection)
    create_vehicles_table(connection)
    connection.execute("DROP TABLE IF EXISTS vehicle_payloads")
    create_vehicle_summary_view(connection)
    connection.commit()


def load_tracked_vins(connection: sqlite3.Connection) -> set[str]:
    return {row["vin"] for row in connection.execute("SELECT vin FROM vehicles")}


def vehicle_db_row(vehicle: dict[str, Any], timestamp: str) -> dict[str, Any]:
    price = vehicle.get("price") or {}
    model = vehicle.get("model") or {}
    int_color = vehicle.get("intColor") or {}
    ext_color = vehicle.get("extColor") or {}
    return {
        "vin": vehicle.get("vin"), "stock_num": vehicle.get("stockNum"),
        "brand": vehicle.get("brand"), "marketing_series": vehicle.get("marketingSeries"),
        "year": vehicle.get("year"), "dealer_cd": vehicle.get("dealerCd"),
        "dealer_marketing_name": vehicle.get("dealerMarketingName"),
        "dealer_website": vehicle.get("dealerWebsite"), "vdp_url": vehicle.get("vdpUrl"),
        "distance": vehicle.get("distance"), "inventory_status": vehicle.get("inventoryStatus"),
        "is_pre_sold": int(bool(vehicle.get("isPreSold"))),
        "total_msrp": price.get("totalMsrp"), "advertized_price": price.get("advertizedPrice"),
        "base_msrp": price.get("baseMsrp"), "dph": price.get("dph"),
        "model_cd": model.get("modelCd"), "model_marketing_name": model.get("marketingName"),
        "model_marketing_title": model.get("marketingTitle"),
        "int_color_cd": int_color.get("colorCd"), "int_color_name": int_color.get("marketingName"),
        "ext_color_cd": ext_color.get("colorCd"), "ext_color_name": ext_color.get("marketingName"),
        "first_seen_at": timestamp, "last_seen_at": timestamp,
    }


def save_vehicles(connection: sqlite3.Connection, vehicles: list[dict[str, Any]]) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    rows = [vehicle_db_row(vehicle, timestamp) for vehicle in vehicles if vehicle.get("vin")]
    connection.executemany(
        """
        INSERT INTO vehicles VALUES (
            :vin, :stock_num, :brand, :marketing_series, :year, :dealer_cd,
            :dealer_marketing_name, :dealer_website, :vdp_url, :distance,
            :inventory_status, :is_pre_sold, :total_msrp, :advertized_price,
            :base_msrp, :dph, :model_cd, :model_marketing_name,
            :model_marketing_title, :int_color_cd, :int_color_name,
            :ext_color_cd, :ext_color_name, :first_seen_at, :last_seen_at
        )
        ON CONFLICT(vin) DO UPDATE SET
            stock_num=excluded.stock_num, brand=excluded.brand,
            marketing_series=excluded.marketing_series, year=excluded.year,
            dealer_cd=excluded.dealer_cd, dealer_marketing_name=excluded.dealer_marketing_name,
            dealer_website=excluded.dealer_website, vdp_url=excluded.vdp_url,
            distance=excluded.distance, inventory_status=excluded.inventory_status,
            is_pre_sold=excluded.is_pre_sold, total_msrp=excluded.total_msrp,
            advertized_price=excluded.advertized_price, base_msrp=excluded.base_msrp,
            dph=excluded.dph, model_cd=excluded.model_cd,
            model_marketing_name=excluded.model_marketing_name,
            model_marketing_title=excluded.model_marketing_title,
            int_color_cd=excluded.int_color_cd, int_color_name=excluded.int_color_name,
            ext_color_cd=excluded.ext_color_cd, ext_color_name=excluded.ext_color_name,
            last_seen_at=excluded.last_seen_at
        """,
        rows,
    )
    connection.commit()
