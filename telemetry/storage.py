import sqlite3
from pathlib import Path
from telemetry.models import TelemetrySnapshot

class TelemetryStorage:
    """Handles time-series storage of telemetry snapshots using SQLite."""
    
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestep INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    is_warmup INTEGER NOT NULL,
                    zone_temp_c REAL,
                    energy_rate_w REAL,
                    iaq_co2_ppm REAL,
                    comfort_pmv REAL
                )
            ''')
            conn.commit()

    def insert_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        """Persist a single telemetry snapshot."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO snapshots (
                    timestep, timestamp, is_warmup, zone_temp_c, energy_rate_w, iaq_co2_ppm, comfort_pmv
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                snapshot.timestep,
                snapshot.timestamp,
                int(snapshot.is_warmup),
                snapshot.zone_temp_c,
                snapshot.energy_rate_w,
                snapshot.iaq_co2_ppm,
                snapshot.comfort_pmv
            ))
            conn.commit()

    def count_snapshots(self) -> int:
        """Return the total number of snapshots in the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT COUNT(*) FROM snapshots')
            return cursor.fetchone()[0]
