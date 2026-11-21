"""SQLite persistence layer for ProdSched Nexus.

Stores and retrieves production jobs, machines, disruption events,
solved schedules, and discrete-event simulation runs.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from data_manager import (
    DATA_DIR,
    MACHINES,
    Job,
    Machine,
    Operation,
    get_default_machines,
    machine_by_id,
)

DEFAULT_DB_PATH = DATA_DIR / "prodsched_nexus.db"


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Return an open SQLite connection with Row row_factory."""
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Create database tables if they do not exist and seed default machines."""
    conn = get_connection(db_path)
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS machines (
                machine_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Operational',
                capabilities TEXT NOT NULL DEFAULT '[]',
                total_available_time_min INTEGER NOT NULL DEFAULT 480
            );

            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                job_name TEXT NOT NULL,
                product TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                priority INTEGER NOT NULL,
                due_min INTEGER NOT NULL,
                is_urgent INTEGER NOT NULL DEFAULT 0,
                arrival_min INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS operations (
                job_id TEXT NOT NULL,
                operation_seq INTEGER NOT NULL,
                operation_name TEXT NOT NULL,
                machine_id TEXT NOT NULL,
                duration_min INTEGER NOT NULL,
                PRIMARY KEY (job_id, operation_seq),
                FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS disruptions (
                disruption_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                description TEXT NOT NULL,
                machine_id TEXT,
                start_min INTEGER,
                duration_min INTEGER,
                job_id TEXT,
                operation_seq INTEGER,
                delay_min INTEGER,
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schedule_history (
                schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_type TEXT NOT NULL,
                solver TEXT NOT NULL,
                status TEXT NOT NULL,
                makespan_min INTEGER,
                best_bound_min INTEGER,
                wall_time_s REAL,
                horizon_min INTEGER,
                created_at TEXT NOT NULL,
                details_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS simulation_history (
                sim_id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_type TEXT NOT NULL,
                simulated_makespan_min REAL,
                completed INTEGER NOT NULL,
                total_waiting_min REAL,
                total_downtime_min REAL,
                created_at TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                events_json TEXT NOT NULL
            );
            """
        )

        # Seed machines if empty
        cursor = conn.execute("SELECT COUNT(*) as count FROM machines")
        if cursor.fetchone()["count"] == 0:
            for machine in get_default_machines():
                conn.execute(
                    """
                    INSERT INTO machines (machine_id, name, description, status, capabilities, total_available_time_min)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        machine.machine_id,
                        machine.name,
                        machine.description,
                        machine.status,
                        json.dumps(list(machine.capabilities)),
                        machine.total_available_time_min,
                    ),
                )
    conn.close()


def save_machines(machines: Sequence[Machine], db_path: Path | str | None = None) -> None:
    """Persist machine records to the database."""
    init_db(db_path)
    conn = get_connection(db_path)
    with conn:
        for m in machines:
            conn.execute(
                """
                INSERT INTO machines (machine_id, name, description, status, capabilities, total_available_time_min)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(machine_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    status=excluded.status,
                    capabilities=excluded.capabilities,
                    total_available_time_min=excluded.total_available_time_min
                """,
                (
                    m.machine_id,
                    m.name,
                    m.description,
                    m.status,
                    json.dumps(list(m.capabilities)),
                    m.total_available_time_min,
                ),
            )
    conn.close()


def load_machines(db_path: Path | str | None = None) -> tuple[Machine, ...]:
    """Retrieve machines from the database, falling back to default catalogue if empty."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute(
        "SELECT machine_id, name, description, status, capabilities, total_available_time_min FROM machines ORDER BY machine_id"
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return get_default_machines()

    machines: list[Machine] = []
    for r in rows:
        try:
            caps = tuple(json.loads(r["capabilities"]))
        except Exception:
            caps = ()
        machines.append(
            Machine(
                machine_id=r["machine_id"],
                name=r["name"],
                description=r["description"],
                status=r["status"],
                capabilities=caps,
                total_available_time_min=int(r["total_available_time_min"]),
            )
        )
    return tuple(machines)


def save_jobs(jobs: Sequence[Job], db_path: Path | str | None = None) -> None:
    """Save all jobs and operations to the database (replaces existing records)."""
    init_db(db_path)
    conn = get_connection(db_path)
    now = datetime.now().isoformat()
    with conn:
        conn.execute("DELETE FROM operations")
        conn.execute("DELETE FROM jobs")
        for job in jobs:
            conn.execute(
                """
                INSERT INTO jobs (job_id, job_name, product, quantity, priority, due_min, is_urgent, arrival_min, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.job_name,
                    job.product,
                    job.quantity,
                    job.priority,
                    job.due_min,
                    1 if getattr(job, "is_urgent", False) else 0,
                    getattr(job, "arrival_min", 0),
                    now,
                ),
            )
            for op in job.operations:
                conn.execute(
                    """
                    INSERT INTO operations (job_id, operation_seq, operation_name, machine_id, duration_min)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        op.job_id,
                        op.operation_seq,
                        op.operation_name,
                        op.machine_id,
                        op.duration_min,
                    ),
                )
    conn.close()


def load_jobs_from_db(db_path: Path | str | None = None) -> tuple[Job, ...]:
    """Retrieve jobs and their ordered operations from the database."""
    init_db(db_path)
    conn = get_connection(db_path)
    job_cursor = conn.execute(
        "SELECT job_id, job_name, product, quantity, priority, due_min, is_urgent, arrival_min FROM jobs ORDER BY job_id"
    )
    job_rows = job_cursor.fetchall()

    if not job_rows:
        conn.close()
        return ()

    jobs: list[Job] = []
    for jr in job_rows:
        job_id = jr["job_id"]
        op_cursor = conn.execute(
            "SELECT operation_seq, operation_name, machine_id, duration_min FROM operations WHERE job_id = ? ORDER BY operation_seq",
            (job_id,),
        )
        operations = tuple(
            Operation(
                job_id=job_id,
                operation_seq=int(orow["operation_seq"]),
                operation_name=orow["operation_name"],
                machine_id=orow["machine_id"],
                duration_min=int(orow["duration_min"]),
            )
            for orow in op_cursor.fetchall()
        )
        jobs.append(
            Job(
                job_id=job_id,
                job_name=jr["job_name"],
                product=jr["product"],
                quantity=int(jr["quantity"]),
                priority=int(jr["priority"]),
                due_min=int(jr["due_min"]),
                operations=operations,
                is_urgent=bool(jr["is_urgent"]),
                arrival_min=int(jr["arrival_min"]),
            )
        )
    conn.close()
    return tuple(jobs)


def log_disruption(disruption_dict: dict[str, Any], db_path: Path | str | None = None) -> None:
    """Record a disruption event to the database."""
    init_db(db_path)
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO disruptions (disruption_id, kind, description, machine_id, start_min, duration_min, job_id, operation_seq, delay_min, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(disruption_id) DO UPDATE SET
                kind=excluded.kind,
                description=excluded.description,
                machine_id=excluded.machine_id,
                start_min=excluded.start_min,
                duration_min=excluded.duration_min,
                job_id=excluded.job_id,
                operation_seq=excluded.operation_seq,
                delay_min=excluded.delay_min,
                timestamp=excluded.timestamp
            """,
            (
                disruption_dict.get("disruption_id"),
                disruption_dict.get("kind"),
                disruption_dict.get("description"),
                disruption_dict.get("machine_id"),
                disruption_dict.get("start_min"),
                disruption_dict.get("duration_min"),
                disruption_dict.get("job_id"),
                disruption_dict.get("operation_seq"),
                disruption_dict.get("delay_min"),
                datetime.now().isoformat(),
            ),
        )
    conn.close()


def load_disruptions(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Retrieve disruption history ordered by timestamp descending."""
    init_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.execute("SELECT * FROM disruptions ORDER BY timestamp DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def clear_disruptions(db_path: Path | str | None = None) -> None:
    """Clear all logged disruptions."""
    init_db(db_path)
    conn = get_connection(db_path)
    with conn:
        conn.execute("DELETE FROM disruptions")
    conn.close()


def log_schedule_result(
    result: Any,
    schedule_type: str = "baseline",
    db_path: Path | str | None = None,
) -> int:
    """Record schedule optimization result into database."""
    init_db(db_path)
    conn = get_connection(db_path)
    now = datetime.now().isoformat()
    ops_data = [
        {
            "job_id": op.job_id,
            "job_name": op.job_name,
            "operation_seq": op.operation_seq,
            "operation_name": op.operation_name,
            "machine_id": op.machine_id,
            "machine_name": op.machine_name,
            "duration_min": op.duration_min,
            "start_min": op.start_min,
            "end_min": op.end_min,
        }
        for op in getattr(result, "operations", ())
    ]
    with conn:
        cur = conn.execute(
            """
            INSERT INTO schedule_history (schedule_type, solver, status, makespan_min, best_bound_min, wall_time_s, horizon_min, created_at, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                schedule_type,
                getattr(result, "solver", "OR-Tools CP-SAT"),
                getattr(result, "status", "UNKNOWN"),
                getattr(result, "makespan_min", None),
                getattr(result, "best_bound_min", None),
                getattr(result, "wall_time_s", 0.0),
                getattr(result, "horizon_min", 0),
                now,
                json.dumps(ops_data),
            ),
        )
        schedule_id = cur.lastrowid
    conn.close()
    return schedule_id


def log_simulation_result(
    sim_result: Any,
    schedule_type: str = "baseline",
    db_path: Path | str | None = None,
) -> int:
    """Record discrete-event simulation run into database."""
    init_db(db_path)
    conn = get_connection(db_path)
    now = datetime.now().isoformat()
    metrics = getattr(sim_result, "summary", lambda: {})()
    events = [asdict(e) if hasattr(e, "__dataclass_fields__") else dict(e) for e in getattr(sim_result, "events", [])]
    with conn:
        cur = conn.execute(
            """
            INSERT INTO simulation_history (schedule_type, simulated_makespan_min, completed, total_waiting_min, total_downtime_min, created_at, metrics_json, events_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                schedule_type,
                getattr(sim_result, "makespan_min", 0.0),
                1 if getattr(sim_result, "completed", True) else 0,
                metrics.get("total_waiting_min", 0.0),
                metrics.get("total_downtime_min", 0.0),
                now,
                json.dumps(metrics),
                json.dumps(events[:500]),  # Store recent events
            ),
        )
        sim_id = cur.lastrowid
    conn.close()
    return sim_id
