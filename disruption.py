"""Disruption management and dynamic rescheduling engine for ProdSched Nexus.

Handles three real-world manufacturing disruption scenarios:
1. Machine Breakdown: Machine failure causing unplanned downtime.
2. Urgent Production Order: High-priority rush order inserted into the schedule.
3. Processing Delay: Operation duration extension due to material hardness, tool wear, etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from data_manager import (
    Job,
    Machine,
    Operation,
    load_jobs,
    machine_by_id,
    machine_catalog,
)
from database import log_disruption
from scheduler import (
    MachineDowntime,
    ScheduledOperation,
    ScheduleResult,
    solve_job_shop,
)


@dataclass(frozen=True)
class Disruption:
    """A shop-floor event that alters baseline scheduling constraints."""

    disruption_id: str
    kind: str  # "MACHINE_BREAKDOWN", "URGENT_JOB", "PROCESSING_DELAY"
    description: str
    machine_id: str | None = None
    start_min: int | None = None
    duration_min: int | None = None
    job_id: str | None = None
    operation_seq: int | None = None
    delay_min: int | None = None
    new_job: Job | None = None
    timestamp: str | None = None


def apply_disruption(
    schedule: ScheduleResult,
    disruption: Disruption,
    base_jobs: Sequence[Job] | None = None,
    machines: Sequence[Machine] | None = None,
) -> ScheduleResult:
    """Apply a single disruption to a baseline schedule and re-optimize with CP-SAT."""
    jobs = tuple(base_jobs) if base_jobs is not None else load_jobs()
    mgr = DisruptionManager()
    mgr.add_disruption(disruption)
    return mgr.reschedule(jobs, machines=machines)


class DisruptionManager:
    """Orchestrates shop-floor disruptions and coordinates rescheduling."""

    def __init__(self) -> None:
        self._disruptions: list[Disruption] = []

    @property
    def disruptions(self) -> tuple[Disruption, ...]:
        return tuple(self._disruptions)

    def add_disruption(self, disruption: Disruption) -> None:
        """Add an arbitrary disruption and persist it."""
        self._disruptions.append(disruption)
        try:
            log_disruption(
                {
                    "disruption_id": disruption.disruption_id,
                    "kind": disruption.kind,
                    "description": disruption.description,
                    "machine_id": disruption.machine_id,
                    "start_min": disruption.start_min,
                    "duration_min": disruption.duration_min,
                    "job_id": disruption.job_id,
                    "operation_seq": disruption.operation_seq,
                    "delay_min": disruption.delay_min,
                }
            )
        except Exception:
            pass

    def add_breakdown(
        self,
        machine_id: str,
        start_min: int,
        duration_min: int,
        reason: str = "Unplanned mechanical failure",
    ) -> Disruption:
        """Register a machine breakdown event."""
        disruption_id = f"BD-{machine_id}-{start_min}-{len(self._disruptions) + 1}"
        desc = f"Machine {machine_id} down at t={start_min} min for {duration_min} min ({reason})"
        d = Disruption(
            disruption_id=disruption_id,
            kind="MACHINE_BREAKDOWN",
            description=desc,
            machine_id=machine_id,
            start_min=int(start_min),
            duration_min=int(duration_min),
            timestamp=datetime.now().isoformat(),
        )
        self.add_disruption(d)
        return d

    def add_urgent_job(self, job: Job, reason: str = "Expedited customer order") -> Disruption:
        """Register a new urgent production order to be inserted into the shop floor."""
        disruption_id = f"URG-{job.job_id}-{len(self._disruptions) + 1}"
        desc = f"Urgent Job {job.job_id} ({job.job_name}) inserted with Priority {job.priority} ({reason})"
        d = Disruption(
            disruption_id=disruption_id,
            kind="URGENT_JOB",
            description=desc,
            job_id=job.job_id,
            new_job=job,
            timestamp=datetime.now().isoformat(),
        )
        self.add_disruption(d)
        return d

    def add_processing_delay(
        self,
        job_id: str,
        operation_seq: int,
        delay_min: int,
        reason: str = "Tool wear / difficult workpiece material",
    ) -> Disruption:
        """Register a processing delay on a specific job operation."""
        disruption_id = f"DLY-{job_id}-OP{operation_seq}-{len(self._disruptions) + 1}"
        desc = f"Job {job_id} Operation {operation_seq} delayed by +{delay_min} min ({reason})"
        d = Disruption(
            disruption_id=disruption_id,
            kind="PROCESSING_DELAY",
            description=desc,
            job_id=job_id,
            operation_seq=int(operation_seq),
            delay_min=int(delay_min),
            timestamp=datetime.now().isoformat(),
        )
        self.add_disruption(d)
        return d

    def remove_disruption(self, disruption_id: str) -> None:
        """Remove a disruption by id."""
        self._disruptions = [d for d in self._disruptions if d.disruption_id != disruption_id]

    def clear(self) -> None:
        """Clear all active disruptions."""
        self._disruptions.clear()

    def get_breakdowns(self, machines: Sequence[Machine] | None = None) -> tuple[MachineDowntime, ...]:
        """Convert machine breakdown disruptions into MachineDowntime intervals."""
        cat = machine_by_id(machines)
        breakdowns: list[MachineDowntime] = []
        for d in self._disruptions:
            if d.kind == "MACHINE_BREAKDOWN" and d.machine_id and d.start_min is not None and d.duration_min is not None:
                machine_name = cat[d.machine_id].name if d.machine_id in cat else d.machine_id
                breakdowns.append(
                    MachineDowntime(
                        machine_id=d.machine_id,
                        machine_name=machine_name,
                        start_min=d.start_min,
                        duration_min=d.duration_min,
                        end_min=d.start_min + d.duration_min,
                        reason=d.description,
                    )
                )
        return tuple(breakdowns)

    def apply_to_jobs(self, base_jobs: Sequence[Job]) -> tuple[Job, ...]:
        """Produce the modified sequence of jobs incorporating processing delays and urgent jobs."""
        # 1. Map cumulative delays per (job_id, operation_seq)
        delays: dict[tuple[str, int], int] = {}
        urgent_jobs: list[Job] = []

        for d in self._disruptions:
            if d.kind == "PROCESSING_DELAY" and d.job_id and d.operation_seq and d.delay_min:
                key = (d.job_id, d.operation_seq)
                delays[key] = delays.get(key, 0) + d.delay_min
            elif d.kind == "URGENT_JOB" and d.new_job:
                urgent_jobs.append(d.new_job)

        # 2. Reconstruct base jobs with extended operation durations
        modified_jobs: list[Job] = []
        for job in base_jobs:
            new_ops: list[Operation] = []
            for op in job.operations:
                extra = delays.get((job.job_id, op.operation_seq), 0)
                new_ops.append(
                    Operation(
                        job_id=op.job_id,
                        operation_seq=op.operation_seq,
                        operation_name=op.operation_name,
                        machine_id=op.machine_id,
                        duration_min=op.duration_min + extra,
                    )
                )
            modified_jobs.append(
                Job(
                    job_id=job.job_id,
                    job_name=job.job_name,
                    product=job.product,
                    quantity=job.quantity,
                    priority=job.priority,
                    due_min=job.due_min,
                    operations=tuple(new_ops),
                    is_urgent=getattr(job, "is_urgent", False),
                    arrival_min=getattr(job, "arrival_min", 0),
                )
            )

        # 3. Append newly inserted urgent jobs (avoiding duplicate job IDs)
        existing_ids = {j.job_id for j in modified_jobs}
        for uj in urgent_jobs:
            if uj.job_id not in existing_ids:
                modified_jobs.append(uj)
                existing_ids.add(uj.job_id)

        return tuple(modified_jobs)

    def reschedule(
        self,
        base_jobs: Sequence[Job],
        machines: Sequence[Machine] | None = None,
        time_limit_s: float = 30.0,
        objective_mode: str = "makespan",
    ) -> ScheduleResult:
        """Apply all disruptions and solve the revised workshop schedule."""
        effective_jobs = self.apply_to_jobs(base_jobs)
        breakdowns = self.get_breakdowns(machines)
        return solve_job_shop(
            effective_jobs,
            machines=machines,
            breakdowns=breakdowns,
            objective_mode=objective_mode,
            time_limit_s=time_limit_s,
        )

    @staticmethod
    def compare_schedules(
        baseline: ScheduleResult,
        revised: ScheduleResult,
        jobs: Sequence[Job] | None = None,
    ) -> dict[str, Any]:
        """Perform quantitative and qualitative comparison between baseline and revised schedules."""
        base_mk = baseline.makespan_min or 0
        rev_mk = revised.makespan_min or 0
        delta_mk = rev_mk - base_mk
        delta_pct = (delta_mk / base_mk * 100.0) if base_mk > 0 else 0.0

        # Completion times by job
        base_job_ends: dict[str, int] = {}
        for op in baseline.operations:
            base_job_ends[op.job_id] = max(base_job_ends.get(op.job_id, 0), op.end_min)

        rev_job_ends: dict[str, int] = {}
        for op in revised.operations:
            rev_job_ends[op.job_id] = max(rev_job_ends.get(op.job_id, 0), op.end_min)

        job_delays: dict[str, int] = {}
        for job_id, rev_end in rev_job_ends.items():
            base_end = base_job_ends.get(job_id)
            if base_end is not None:
                diff = rev_end - base_end
                if diff > 0:
                    job_delays[job_id] = diff

        # Tardiness relative to due dates
        due_dates: dict[str, int] = {}
        if jobs is not None:
            due_dates = {j.job_id: j.due_min for j in jobs}

        delayed_against_due: list[dict[str, Any]] = []
        for job_id, rev_end in rev_job_ends.items():
            due = due_dates.get(job_id)
            if due is not None and rev_end > due:
                delayed_against_due.append(
                    {
                        "job_id": job_id,
                        "due_min": due,
                        "completion_min": rev_end,
                        "tardiness_min": rev_end - due,
                    }
                )

        # Generate diagnostic explanation narrative
        narrative_parts = []
        if delta_mk > 0:
            narrative_parts.append(
                f"Production makespan extended from {base_mk} min to {rev_mk} min (+{delta_mk} min, +{delta_pct:.1f}%)."
            )
        elif delta_mk == 0:
            narrative_parts.append(f"Production makespan was successfully preserved at {base_mk} min.")
        else:
            narrative_parts.append(f"Revised makespan shortened to {rev_mk} min (delta: {delta_mk} min).")

        if revised.downtimes:
            total_dt = sum(d.duration_min for d in revised.downtimes)
            machines_hit = {d.machine_name for d in revised.downtimes}
            narrative_parts.append(
                f"{len(revised.downtimes)} machine breakdown(s) caused {total_dt} min of downtime on {', '.join(machines_hit)}."
            )

        if job_delays:
            delayed_str = ", ".join(f"{jid} (+{dmin}m)" for jid, dmin in sorted(job_delays.items()))
            narrative_parts.append(f"{len(job_delays)} existing jobs experienced schedule delays: {delayed_str}.")
        else:
            narrative_parts.append("No existing jobs were pushed past their original completion targets.")

        if delayed_against_due:
            tardy_str = ", ".join(f"{item['job_id']} by {item['tardiness_min']}m" for item in delayed_against_due)
            narrative_parts.append(f"CRITICAL: {len(delayed_against_due)} job(s) breached delivery deadlines: {tardy_str}.")

        explanation = " ".join(narrative_parts)

        return {
            "baseline_makespan_min": base_mk,
            "revised_makespan_min": rev_mk,
            "makespan_delta_min": delta_mk,
            "makespan_delta_pct": delta_pct,
            "job_delays": job_delays,
            "tardy_jobs": delayed_against_due,
            "explanation": explanation,
            "downtimes_count": len(revised.downtimes),
            "total_downtime_min": sum(d.duration_min for d in revised.downtimes),
        }
