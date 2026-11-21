"""CP-SAT job-shop scheduler for ProdSched Nexus.

The model is a classic job shop solved with Google OR-Tools CP-SAT:

- each operation has a start time on its assigned machine
- operations of one job keep their sequence
- a machine processes at most one operation at a time
- machine downtime intervals (breakdowns) are enforced via fixed interval variables
- the primary objective is schedule makespan, with optional weighted tardiness support
- all start and end times come from the solver
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pandas as pd
from ortools.sat.python import cp_model

from data_manager import Job, Machine, machine_by_id, machine_catalog, validate_jobs

SOLVER_NAME = "OR-Tools CP-SAT"


@dataclass(frozen=True)
class MachineDowntime:
    """A fixed machine downtime interval resulting from a breakdown or maintenance."""

    machine_id: str
    machine_name: str
    start_min: int
    duration_min: int
    end_min: int
    reason: str = "Unplanned breakdown"


@dataclass(frozen=True)
class ScheduledOperation:
    """One operation placed in time by the CP-SAT solver."""

    job_id: str
    job_name: str
    operation_seq: int
    operation_name: str
    machine_id: str
    machine_name: str
    duration_min: int
    start_min: int
    end_min: int
    is_urgent: bool = False


@dataclass(frozen=True)
class ScheduleResult:
    """Optimal or feasible timetable returned by CP-SAT."""

    solver: str
    status: str
    makespan_min: int | None
    best_bound_min: int | None
    wall_time_s: float
    horizon_min: int
    operations: tuple[ScheduledOperation, ...]
    downtimes: tuple[MachineDowntime, ...] = ()
    is_disrupted: bool = False
    objective_value: float | None = None

    @property
    def solved(self) -> bool:
        return self.status in {"OPTIMAL", "FEASIBLE"} and self.makespan_min is not None

    def to_dataframe(self) -> pd.DataFrame:
        rows = [
            {
                "job_id": operation.job_id,
                "job_name": operation.job_name,
                "operation_seq": operation.operation_seq,
                "operation_name": operation.operation_name,
                "machine_id": operation.machine_id,
                "machine_name": operation.machine_name,
                "duration_min": operation.duration_min,
                "start_min": operation.start_min,
                "end_min": operation.end_min,
                "is_urgent": operation.is_urgent,
            }
            for operation in self.operations
        ]
        return pd.DataFrame(rows)


@dataclass(frozen=True)
class _CompiledModel:
    model: cp_model.CpModel
    starts: dict[tuple[str, int], cp_model.IntVar]
    ends: dict[tuple[str, int], cp_model.IntVar]
    makespan: cp_model.IntVar
    horizon: int
    machines_with_work: tuple[str, ...]


class ScheduleError(RuntimeError):
    """Raised when a solved timetable violates the job-shop constraints."""


def solve_job_shop(
    jobs: tuple[Job, ...] | list[Job],
    *,
    machines: tuple[Machine, ...] | None = None,
    breakdowns: Sequence[MachineDowntime] | None = None,
    objective_mode: str = "makespan",
    time_limit_s: float = 30.0,
    random_seed: int = 1,
) -> ScheduleResult:
    """Solve the job shop problem using Google OR-Tools CP-SAT."""
    job_list = tuple(jobs)
    machine_list = tuple(machines) if machines is not None else machine_catalog()
    validate_jobs(job_list, machine_list)
    compiled = build_job_shop_model(
        job_list,
        machine_list,
        breakdowns=breakdowns,
        objective_mode=objective_mode,
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.random_seed = random_seed
    solver.parameters.num_search_workers = 8

    status_code = solver.Solve(compiled.model)
    status = solver.StatusName(status_code)
    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ScheduleResult(
            solver=SOLVER_NAME,
            status=status,
            makespan_min=None,
            best_bound_min=None,
            wall_time_s=solver.WallTime(),
            horizon_min=compiled.horizon,
            operations=(),
            downtimes=tuple(breakdowns) if breakdowns else (),
            is_disrupted=bool(breakdowns),
        )

    names = {machine.machine_id: machine.name for machine in machine_list}
    job_names = {job.job_id: job.job_name for job in job_list}
    scheduled: list[ScheduledOperation] = []
    for job in job_list:
        is_urg = getattr(job, "is_urgent", False)
        for operation in job.operations:
            key = (job.job_id, operation.operation_seq)
            start = int(solver.Value(compiled.starts[key]))
            end = int(solver.Value(compiled.ends[key]))
            scheduled.append(
                ScheduledOperation(
                    job_id=job.job_id,
                    job_name=job_names[job.job_id],
                    operation_seq=operation.operation_seq,
                    operation_name=operation.operation_name,
                    machine_id=operation.machine_id,
                    machine_name=names[operation.machine_id],
                    duration_min=operation.duration_min,
                    start_min=start,
                    end_min=end,
                    is_urgent=is_urg,
                )
            )

    scheduled.sort(key=lambda item: (item.machine_id, item.start_min, item.job_id, item.operation_seq))
    makespan = int(solver.Value(compiled.makespan))
    best_bound = int(solver.BestObjectiveBound()) if status_code == cp_model.OPTIMAL else None

    downtime_list = tuple(breakdowns) if breakdowns else ()
    result = ScheduleResult(
        solver=SOLVER_NAME,
        status=status,
        makespan_min=makespan,
        best_bound_min=best_bound if best_bound is not None else makespan,
        wall_time_s=solver.WallTime(),
        horizon_min=compiled.horizon,
        operations=tuple(scheduled),
        downtimes=downtime_list,
        is_disrupted=bool(downtime_list),
        objective_value=float(solver.ObjectiveValue()),
    )
    validate_schedule(job_list, result, breakdowns=downtime_list)
    return result


def build_job_shop_model(
    jobs: tuple[Job, ...] | list[Job],
    machines: tuple[Machine, ...] | None = None,
    breakdowns: Sequence[MachineDowntime] | None = None,
    objective_mode: str = "makespan",
) -> _CompiledModel:
    """Build the CP-SAT job-shop model without solving it."""
    job_list = tuple(jobs)
    machine_list = tuple(machines) if machines is not None else machine_catalog()
    validate_jobs(job_list, machine_list)

    total_op_duration = sum(operation.duration_min for job in job_list for operation in job.operations)
    breakdown_list = tuple(breakdowns) if breakdowns else ()

    # Keep horizon exact when no breakdowns, otherwise extend safely
    if breakdown_list:
        max_breakdown_end = max((b.end_min for b in breakdown_list), default=0)
        total_breakdown = sum(b.duration_min for b in breakdown_list)
        horizon = total_op_duration + total_breakdown + max_breakdown_end
    else:
        horizon = total_op_duration

    model = cp_model.CpModel()
    starts: dict[tuple[str, int], cp_model.IntVar] = {}
    ends: dict[tuple[str, int], cp_model.IntVar] = {}
    intervals_by_machine: dict[str, list[cp_model.IntervalVar]] = {
        machine.machine_id: [] for machine in machine_list
    }

    # Operation intervals and precedence constraints
    for job in job_list:
        previous_end: cp_model.IntVar | None = None
        for operation in job.operations:
            key = (job.job_id, operation.operation_seq)
            suffix = f"{job.job_id}_op{operation.operation_seq}"
            start = model.NewIntVar(0, horizon, f"start_{suffix}")
            end = model.NewIntVar(0, horizon, f"end_{suffix}")
            interval = model.NewIntervalVar(
                start,
                operation.duration_min,
                end,
                f"interval_{suffix}",
            )
            starts[key] = start
            ends[key] = end
            intervals_by_machine[operation.machine_id].append(interval)
            if previous_end is not None:
                model.Add(start >= previous_end)
            previous_end = end

    # Fixed machine downtime intervals (breakdowns)
    for b_idx, b in enumerate(breakdown_list):
        if b.machine_id in intervals_by_machine:
            d_start = model.NewConstant(b.start_min)
            d_end = model.NewConstant(b.end_min)
            d_interval = model.NewIntervalVar(
                d_start,
                b.duration_min,
                d_end,
                f"downtime_{b.machine_id}_{b_idx}",
            )
            intervals_by_machine[b.machine_id].append(d_interval)

    # Machine no-overlap constraints
    machines_with_work: list[str] = []
    for machine in machine_list:
        intervals = intervals_by_machine[machine.machine_id]
        if not intervals:
            continue
        model.AddNoOverlap(intervals)
        machines_with_work.append(machine.machine_id)

    # Makespan variable
    makespan = model.NewIntVar(0, horizon, "makespan")
    for job in job_list:
        last = job.operations[-1]
        model.Add(makespan >= ends[(job.job_id, last.operation_seq)])

    # Optimization objective
    if objective_mode == "makespan":
        model.Minimize(makespan)
    elif objective_mode == "weighted_priority":
        # Multi-objective: minimize makespan + weighted completion time by priority
        weighted_costs = [makespan]
        for job in job_list:
            last = job.operations[-1]
            last_end = ends[(job.job_id, last.operation_seq)]
            priority_mult = max(1, 4 - job.priority)  # priority 1 -> 3, priority 2 -> 2, priority 3 -> 1
            weighted_costs.append(priority_mult * last_end)
        model.Minimize(sum(weighted_costs))
    else:
        model.Minimize(makespan)

    return _CompiledModel(
        model=model,
        starts=starts,
        ends=ends,
        makespan=makespan,
        horizon=horizon,
        machines_with_work=tuple(machines_with_work),
    )


def validate_schedule(
    jobs: tuple[Job, ...] | list[Job],
    result: ScheduleResult,
    breakdowns: Sequence[MachineDowntime] | None = None,
) -> None:
    """Raise ``ScheduleError`` if machine overlap, downtime violation, or broken route occurs."""
    if not result.solved:
        raise ScheduleError(f"Schedule status {result.status} has no timetable.")

    job_list = tuple(jobs)
    expected: dict[tuple[str, int], tuple[str, int]] = {}
    for job in job_list:
        for operation in job.operations:
            expected[(job.job_id, operation.operation_seq)] = (
                operation.machine_id,
                operation.duration_min,
            )

    found = {(item.job_id, item.operation_seq): item for item in result.operations}
    if set(found) != set(expected):
        raise ScheduleError("Scheduled operations do not match the job definitions.")

    for key, (machine_id, duration) in expected.items():
        item = found[key]
        if item.machine_id != machine_id:
            raise ScheduleError(
                f"{key[0]} operation {key[1]} moved from {machine_id} to {item.machine_id}."
            )
        if item.end_min - item.start_min != duration or item.duration_min != duration:
            raise ScheduleError(
                f"{key[0]} operation {key[1]} does not span its processing time."
            )
        if item.start_min < 0:
            raise ScheduleError(f"{key[0]} operation {key[1]} starts before time zero.")

    # Machine no-overlap validation
    by_machine: dict[str, list[ScheduledOperation]] = {}
    for item in result.operations:
        by_machine.setdefault(item.machine_id, []).append(item)
    for machine_id, items in by_machine.items():
        ordered = sorted(items, key=lambda item: (item.start_min, item.end_min, item.job_id))
        for previous, current in zip(ordered, ordered[1:]):
            if previous.end_min > current.start_min:
                raise ScheduleError(
                    f"Machine {machine_id} overlaps "
                    f"{previous.job_id} op {previous.operation_seq} "
                    f"[{previous.start_min}, {previous.end_min}) and "
                    f"{current.job_id} op {current.operation_seq} "
                    f"[{current.start_min}, {current.end_min})."
                )

    # Breakdown non-overlap validation
    downtimes = tuple(breakdowns) if breakdowns else result.downtimes
    for b in downtimes:
        ops_on_machine = by_machine.get(b.machine_id, [])
        for op in ops_on_machine:
            if op.start_min < b.end_min and op.end_min > b.start_min:
                raise ScheduleError(
                    f"Operation {op.job_id} op {op.operation_seq} [{op.start_min}, {op.end_min}) "
                    f"overlaps breakdown on {b.machine_id} [{b.start_min}, {b.end_min})."
                )

    # Job sequence precedence validation
    jobs_by_id = {job.job_id: job for job in job_list}
    for job_id, job in jobs_by_id.items():
        for earlier, later in zip(job.operations, job.operations[1:]):
            before = found[(job_id, earlier.operation_seq)]
            after = found[(job_id, later.operation_seq)]
            if before.end_min > after.start_min:
                raise ScheduleError(
                    f"Job {job_id} runs operation {later.operation_seq} "
                    f"before operation {earlier.operation_seq} has finished."
                )

    ends = [item.end_min for item in result.operations]
    if result.makespan_min != max(ends):
        raise ScheduleError(
            f"Makespan {result.makespan_min} is not the last operation end {max(ends)}."
        )


def lower_bound_min(jobs: tuple[Job, ...] | list[Job]) -> int:
    """Return max(machine load, longest job). A feasible makespan cannot be smaller."""
    loads: dict[str, int] = {}
    longest_job = 0
    for job in jobs:
        longest_job = max(longest_job, job.total_duration_min)
        for operation in job.operations:
            loads[operation.machine_id] = loads.get(operation.machine_id, 0) + operation.duration_min
    return max([longest_job, *loads.values()] or [0])


def format_schedule(result: ScheduleResult) -> str:
    """Plain-text timetable for the console."""
    lines = [
        f"Solver: {result.solver}",
        f"Status: {result.status}",
        f"Makespan: {result.makespan_min} min",
        f"Best bound: {result.best_bound_min} min",
        f"Wall time: {result.wall_time_s:.4f} s",
        f"Horizon: {result.horizon_min} min",
        "",
    ]
    if result.downtimes:
        lines.append("Machine Downtimes:")
        for dt in result.downtimes:
            lines.append(f"  {dt.machine_name} ({dt.machine_id}): {dt.start_min}-{dt.end_min} min ({dt.reason})")
        lines.append("")

    frame = result.to_dataframe()
    if frame.empty:
        lines.append("No operations were scheduled.")
        return "\n".join(lines)

    display = frame.sort_values(
        ["start_min", "machine_id", "job_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    lines.append(display.to_string(index=False))
    lines.append("")
    lines.append("By machine:")
    names = machine_by_id()
    for machine_id, group in frame.groupby("machine_id", sort=False):
        machine_name = names.get(machine_id).name if machine_id in names else machine_id
        lines.append(f"  {machine_name}")
        ordered = group.sort_values("start_min", kind="mergesort")
        for row in ordered.itertuples(index=False):
            lines.append(
                f"    {row.start_min:4d}-{row.end_min:<4d}  {row.job_id}  "
                f"op {row.operation_seq}  {row.operation_name}"
            )
    return "\n".join(lines)


def main() -> None:
    from data_manager import load_jobs

    jobs = load_jobs()
    result = solve_job_shop(jobs)
    print(format_schedule(result))


if __name__ == "__main__":
    main()
