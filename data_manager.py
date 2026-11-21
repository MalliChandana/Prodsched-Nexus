"""Load, manage, and validate workshop jobs and machines for ProdSched Nexus.

Jobs are read from ``data/production_jobs.csv`` or the SQLite store.
Each row in the tabular representation is one operation.
Machines are the workshop resources (Cutting, Drilling, Finishing, etc.);
every operation must name an eligible machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
JOBS_PATH = DATA_DIR / "production_jobs.csv"

REQUIRED_COLUMNS = (
    "job_id",
    "job_name",
    "product",
    "quantity",
    "priority",
    "due_min",
    "operation_seq",
    "operation_name",
    "machine_id",
    "machine_name",
    "duration_min",
)


@dataclass(frozen=True)
class Machine:
    """A workshop resource that processes one operation at a time."""

    machine_id: str
    name: str
    description: str
    status: str = "Operational"  # Operational, Maintenance, Breakdown, Idle
    capabilities: tuple[str, ...] = ()
    total_available_time_min: int = 480  # Default 8-hour shift horizon


@dataclass(frozen=True)
class Operation:
    """One step of a job, assigned to a specific machine."""

    job_id: str
    operation_seq: int
    operation_name: str
    machine_id: str
    duration_min: int


@dataclass(frozen=True)
class Job:
    """A production order and the sequence of operations that completes it.

    ``duration_min`` on each operation is the total lot processing time.
    ``priority`` uses 1 as the highest urgency rank (1 = critical, 2 = high, 3 = normal).
    ``due_min`` is the promised delivery deadline from time zero.
    """

    job_id: str
    job_name: str
    product: str
    quantity: int
    priority: int
    due_min: int
    operations: tuple[Operation, ...]
    is_urgent: bool = False
    arrival_min: int = 0

    @property
    def total_duration_min(self) -> int:
        return sum(operation.duration_min for operation in self.operations)


MACHINES: tuple[Machine, ...] = (
    Machine(
        "CUT",
        "Cutting",
        "Bandsaw station for blanks and bar stock",
        status="Operational",
        capabilities=("Bandsaw Cutting", "Blanking", "Bar Stock Sizing"),
    ),
    Machine(
        "DRL",
        "Drilling",
        "Drill press for holes, bores, and bolt circles",
        status="Operational",
        capabilities=("Hole Drilling", "Boring", "Fastener Patterns"),
    ),
    Machine(
        "FIN",
        "Finishing",
        "Deburr, face, and finish station",
        status="Operational",
        capabilities=("Deburring", "Surface Facing", "Journal Polishing"),
    ),
)


class DataError(ValueError):
    """Raised when the job file or workshop catalogue is inconsistent."""


def machine_catalog() -> tuple[Machine, ...]:
    """Return the workshop machines in stable display order."""
    return MACHINES


def get_default_machines() -> tuple[Machine, ...]:
    """Return default workshop machine definitions."""
    return MACHINES


def machine_by_id(machines: Sequence[Machine] | None = None) -> dict[str, Machine]:
    """Map machine_id to Machine object."""
    cat = machines if machines is not None else MACHINES
    return {machine.machine_id: machine for machine in cat}


def load_jobs(path: Path | None = None) -> tuple[Job, ...]:
    """Load jobs from the production CSV and validate them."""
    jobs_path = Path(path) if path is not None else JOBS_PATH
    frame = _read_jobs_frame(jobs_path)
    jobs = _jobs_from_frame(frame)
    validate_jobs(jobs)
    return jobs


def load_jobs_frame(path: Path | None = None) -> pd.DataFrame:
    """Return the raw operation table, typed and ordered."""
    jobs_path = Path(path) if path is not None else JOBS_PATH
    return _read_jobs_frame(jobs_path)


def jobs_to_dataframe(
    jobs: Sequence[Job],
    machines: Sequence[Machine] | None = None,
) -> pd.DataFrame:
    """Convert a sequence of Job objects to a flat tabular DataFrame."""
    cat = machine_by_id(machines)
    rows: list[dict] = []
    for job in jobs:
        for op in job.operations:
            machine_name = cat[op.machine_id].name if op.machine_id in cat else op.machine_id
            rows.append(
                {
                    "job_id": job.job_id,
                    "job_name": job.job_name,
                    "product": job.product,
                    "quantity": job.quantity,
                    "priority": job.priority,
                    "due_min": job.due_min,
                    "operation_seq": op.operation_seq,
                    "operation_name": op.operation_name,
                    "machine_id": op.machine_id,
                    "machine_name": machine_name,
                    "duration_min": op.duration_min,
                    "is_urgent": getattr(job, "is_urgent", False),
                }
            )
    return pd.DataFrame(rows)


def save_jobs_to_csv(
    jobs: Sequence[Job],
    path: Path | None = None,
    machines: Sequence[Machine] | None = None,
) -> None:
    """Write current jobs to a CSV file matching the standard schema."""
    jobs_path = Path(path) if path is not None else JOBS_PATH
    frame = jobs_to_dataframe(jobs, machines)
    export_cols = list(REQUIRED_COLUMNS)
    frame.to_csv(jobs_path, columns=export_cols, index=False)


def reset_sample_data(path: Path | None = None) -> tuple[Job, ...]:
    """Restore the canonical 5-job, 13-operation sample dataset."""
    sample_csv_content = (
        "job_id,job_name,product,quantity,priority,due_min,operation_seq,operation_name,machine_id,machine_name,duration_min\n"
        "J-101,Support Bracket,Mild-steel support bracket,4,1,220,1,Saw bracket blank,CUT,Cutting,45\n"
        "J-101,Support Bracket,Mild-steel support bracket,4,1,220,2,Drill mounting holes,DRL,Drilling,30\n"
        "J-101,Support Bracket,Mild-steel support bracket,4,1,220,3,Deburr and finish edges,FIN,Finishing,20\n"
        "J-102,Drive Shaft,Alloy drive shaft,2,1,280,1,Cut bar to length,CUT,Cutting,60\n"
        "J-102,Drive Shaft,Alloy drive shaft,2,1,280,2,Drill cross holes,DRL,Drilling,40\n"
        "J-102,Drive Shaft,Alloy drive shaft,2,1,280,3,Finish bearing journals,FIN,Finishing,25\n"
        "J-103,Gear Blank,Hobbed gear blank,3,2,260,1,Cut gear blank,CUT,Cutting,55\n"
        "J-103,Gear Blank,Hobbed gear blank,3,2,260,2,Face and finish,FIN,Finishing,35\n"
        "J-103,Gear Blank,Hobbed gear blank,3,2,260,3,Drill centre bore,DRL,Drilling,22\n"
        "J-104,Cover Panel,Pre-cut cover panel,6,2,190,1,Drill fastener pattern,DRL,Drilling,28\n"
        "J-104,Cover Panel,Pre-cut cover panel,6,2,190,2,Finish panel edges,FIN,Finishing,32\n"
        "J-105,Cast Flange,Cast iron flange,5,3,170,1,Machine mating face,FIN,Finishing,24\n"
        "J-105,Cast Flange,Cast iron flange,5,3,170,2,Drill bolt circle,DRL,Drilling,36\n"
    )
    jobs_path = Path(path) if path is not None else JOBS_PATH
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    jobs_path.write_text(sample_csv_content, encoding="utf-8")
    return load_jobs(jobs_path)


def validate_jobs(
    jobs: tuple[Job, ...] | list[Job],
    machines: tuple[Machine, ...] | None = None,
) -> None:
    """Check job identity, contiguous sequences, and machine assignment."""
    if not jobs:
        raise DataError("At least one production job is required.")

    catalogue = machine_by_id() if machines is None else {
        machine.machine_id: machine for machine in machines
    }
    if len(catalogue) != len(tuple(machines) if machines is not None else MACHINES):
        raise DataError("Machine ids must be unique.")

    seen_jobs: set[str] = set()
    for job in jobs:
        if job.job_id in seen_jobs:
            raise DataError(f"Duplicate job id {job.job_id}.")
        seen_jobs.add(job.job_id)
        if not job.job_name.strip():
            raise DataError(f"Job {job.job_id} is missing a name.")
        if job.quantity <= 0:
            raise DataError(f"Job {job.job_id} quantity must be positive.")
        if job.priority <= 0:
            raise DataError(f"Job {job.job_id} priority must be positive.")
        if job.due_min < 0:
            raise DataError(f"Job {job.job_id} due time cannot be negative.")
        if not job.operations:
            raise DataError(f"Job {job.job_id} has no operations.")

        sequences = [operation.operation_seq for operation in job.operations]
        expected = list(range(1, len(job.operations) + 1))
        if sequences != expected:
            raise DataError(
                f"Job {job.job_id} operations must be contiguous from 1, "
                f"got {sequences}."
            )
        for operation in job.operations:
            if operation.job_id != job.job_id:
                raise DataError(
                    f"Operation {operation.operation_seq} on {job.job_id} "
                    "carries a different job id."
                )
            if operation.duration_min <= 0:
                raise DataError(
                    f"Job {job.job_id} operation {operation.operation_seq} "
                    "duration must be a positive number of minutes."
                )
            machine = catalogue.get(operation.machine_id)
            if machine is None:
                raise DataError(
                    f"Job {job.job_id} operation {operation.operation_seq} "
                    f"uses unknown machine {operation.machine_id}."
                )


def _read_jobs_frame(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise DataError(f"Production job file not found: {path}")

    frame = pd.read_csv(path)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise DataError(f"Production job file is missing columns: {missing}")
    if frame.empty:
        raise DataError(f"Production job file has no operations: {path}")

    frame = frame.loc[:, list(REQUIRED_COLUMNS)].copy()
    for column in ("job_id", "job_name", "product", "operation_name", "machine_id", "machine_name"):
        frame[column] = frame[column].astype(str).str.strip()
    for column in ("quantity", "priority", "due_min", "operation_seq", "duration_min"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(int)

    frame = frame.sort_values(["job_id", "operation_seq"], kind="mergesort").reset_index(drop=True)
    _validate_frame_consistency(frame)
    return frame


def _validate_frame_consistency(frame: pd.DataFrame) -> None:
    catalogue = machine_by_id()
    for row in frame.itertuples(index=False):
        machine = catalogue.get(row.machine_id)
        if machine is None:
            raise DataError(f"Unknown machine_id {row.machine_id!r} in the job file.")
        if row.machine_name != machine.name:
            raise DataError(
                f"machine_name {row.machine_name!r} does not match catalogue "
                f"name {machine.name!r} for {row.machine_id}."
            )

    identity = ["job_name", "product", "quantity", "priority", "due_min"]
    for job_id, group in frame.groupby("job_id", sort=False):
        for column in identity:
            values = group[column].unique().tolist()
            if len(values) != 1:
                raise DataError(
                    f"Job {job_id} has conflicting {column} values: {values}."
                )
        sequences = group["operation_seq"].tolist()
        if len(sequences) != len(set(sequences)):
            raise DataError(f"Job {job_id} has a duplicate operation sequence.")


def _jobs_from_frame(frame: pd.DataFrame) -> tuple[Job, ...]:
    jobs: list[Job] = []
    for job_id, group in frame.groupby("job_id", sort=False):
        first = group.iloc[0]
        operations = tuple(
            Operation(
                job_id=str(job_id),
                operation_seq=int(row.operation_seq),
                operation_name=str(row.operation_name),
                machine_id=str(row.machine_id),
                duration_min=int(row.duration_min),
            )
            for row in group.itertuples(index=False)
        )
        jobs.append(
            Job(
                job_id=str(job_id),
                job_name=str(first["job_name"]),
                product=str(first["product"]),
                quantity=int(first["quantity"]),
                priority=int(first["priority"]),
                due_min=int(first["due_min"]),
                operations=operations,
            )
        )
    return tuple(jobs)
