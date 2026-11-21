"""Discrete-Event Simulation (DES) engine for ProdSched Nexus using SimPy.

Simulates shop-floor execution with:
- Job arrivals and operation routing
- Machine allocation and waiting queues
- Realistic machine breakdowns using preemptive resources
- Resumption of interrupted jobs upon machine recovery
- Tracking of waiting times, idle times, busy times, and deadline violations
- Direct comparison between planned schedule and simulated execution
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Sequence

import pandas as pd
import simpy

from data_manager import (
    Job,
    Machine,
    Operation,
    load_jobs,
    machine_by_id,
    machine_catalog,
)
from database import log_simulation_result
from disruption import Disruption
from scheduler import MachineDowntime, ScheduleResult


@dataclass(frozen=True)
class SimulationEvent:
    """An event logged during the discrete-event simulation."""

    time_min: float
    event_type: str  # JOB_ARRIVED, OP_QUEUED, OP_STARTED, OP_PREEMPTED, OP_RESUMED, OP_COMPLETED, JOB_COMPLETED, BREAKDOWN_START, BREAKDOWN_END
    job_id: str | None = None
    operation_seq: int | None = None
    machine_id: str | None = None
    details: str = ""


@dataclass
class SimulationResult:
    """Quantitative performance data and event log from a SimPy simulation run."""

    makespan_min: float = 0.0
    completed: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)
    events: list[SimulationEvent] = field(default_factory=list)
    job_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    machine_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    operations_timeline: list[dict[str, Any]] = field(default_factory=list)

    def to_dataframe(self) -> pd.DataFrame:
        """Return the executed operations timeline as a DataFrame."""
        return pd.DataFrame(self.operations_timeline)

    def events_dataframe(self) -> pd.DataFrame:
        """Return all logged events as a DataFrame."""
        rows = [
            {
                "time_min": round(e.time_min, 2),
                "event_type": e.event_type,
                "job_id": e.job_id or "-",
                "operation_seq": e.operation_seq or "-",
                "machine_id": e.machine_id or "-",
                "details": e.details,
            }
            for e in self.events
        ]
        return pd.DataFrame(rows)

    def summary(self) -> dict[str, Any]:
        """Return summary statistics."""
        total_waiting = sum(m.get("total_waiting_min", 0.0) for m in self.job_metrics.values())
        total_downtime = sum(m.get("downtime_min", 0.0) for m in self.machine_metrics.values())
        tardy_jobs = [jid for jid, m in self.job_metrics.items() if m.get("is_tardy", False)]
        avg_util = (
            sum(m.get("utilization_pct", 0.0) for m in self.machine_metrics.values()) / len(self.machine_metrics)
            if self.machine_metrics
            else 0.0
        )
        return {
            "makespan_min": round(self.makespan_min, 2),
            "completed": self.completed,
            "total_waiting_min": round(total_waiting, 2),
            "total_downtime_min": round(total_downtime, 2),
            "tardy_jobs_count": len(tardy_jobs),
            "tardy_jobs": tardy_jobs,
            "average_machine_utilization_pct": round(avg_util, 2),
            "event_count": len(self.events),
        }


class WorkshopSimulator:
    """Discrete-event workshop simulator orchestrated by SimPy."""

    def __init__(
        self,
        schedule: ScheduleResult | None = None,
        jobs: Sequence[Job] | None = None,
        machines: Sequence[Machine] | None = None,
        disruptions: Sequence[Disruption] | None = None,
    ) -> None:
        self.schedule = schedule
        self.machines = tuple(machines) if machines is not None else machine_catalog()
        self.disruptions = tuple(disruptions) if disruptions is not None else ()

        if jobs is not None:
            self.jobs = tuple(jobs)
        elif schedule is not None:
            self.jobs = load_jobs()
        else:
            self.jobs = load_jobs()

    def run(
        self,
        replications: int = 1,
        seed: int = 42,
        stochastic: bool = False,
        variation_pct: float = 0.05,
        dispatch_mode: str = "schedule_paced",  # "schedule_paced" or "opportunistic"
    ) -> SimulationResult:
        """Execute the SimPy discrete-event simulation."""
        random.seed(seed)
        env = simpy.Environment()

        events: list[SimulationEvent] = []

        def log_event(
            event_type: str,
            job_id: str | None = None,
            operation_seq: int | None = None,
            machine_id: str | None = None,
            details: str = "",
        ) -> None:
            events.append(
                SimulationEvent(
                    time_min=round(env.now, 3),
                    event_type=event_type,
                    job_id=job_id,
                    operation_seq=operation_seq,
                    machine_id=machine_id,
                    details=details,
                )
            )

        # Machine resources (PreemptiveResource for realistic machine breakdowns)
        machine_resources: dict[str, simpy.PreemptiveResource] = {
            m.machine_id: simpy.PreemptiveResource(env, capacity=1) for m in self.machines
        }
        machine_busy_time: dict[str, float] = {m.machine_id: 0.0 for m in self.machines}
        machine_downtime: dict[str, float] = {m.machine_id: 0.0 for m in self.machines}
        machine_ops_count: dict[str, int] = {m.machine_id: 0 for m in self.machines}
        machine_bd_count: dict[str, int] = {m.machine_id: 0 for m in self.machines}

        # Planned start lookup from CP-SAT schedule (if provided) to guide dispatch ordering
        planned_starts: dict[tuple[str, int], int] = {}
        if self.schedule and self.schedule.operations:
            for op in self.schedule.operations:
                planned_starts[(op.job_id, op.operation_seq)] = op.start_min

        # Operation timeline recordings
        op_timelines: list[dict[str, Any]] = []
        job_starts: dict[str, float] = {}
        job_completions: dict[str, float] = {}
        job_wait_times: dict[str, float] = {j.job_id: 0.0 for j in self.jobs}
        job_proc_times: dict[str, float] = {j.job_id: 0.0 for j in self.jobs}

        # 1. Schedule Machine Breakdowns
        # Breakdowns take preemptive priority -100
        def breakdown_process(b_machine_id: str, start_t: float, dur: float, reason: str):
            if start_t > env.now:
                yield env.timeout(start_t - env.now)
            m_res = machine_resources[b_machine_id]
            log_event(
                "BREAKDOWN_START",
                machine_id=b_machine_id,
                details=f"Machine {b_machine_id} failed: {reason} (duration {dur} min)",
            )
            t_bd_start = env.now
            machine_bd_count[b_machine_id] += 1
            # Request resource with highest preemption priority
            with m_res.request(priority=-100, preempt=True) as req:
                yield req
                yield env.timeout(dur)
            actual_bd = env.now - t_bd_start
            machine_downtime[b_machine_id] += actual_bd
            log_event(
                "BREAKDOWN_END",
                machine_id=b_machine_id,
                details=f"Machine {b_machine_id} restored to service after {actual_bd:.1f} min downtime",
            )

        # Launch breakdown processes from disruptions
        for d in self.disruptions:
            if (
                d.kind == "MACHINE_BREAKDOWN"
                and d.machine_id in machine_resources
                and d.start_min is not None
                and d.duration_min is not None
            ):
                env.process(
                    breakdown_process(
                        d.machine_id,
                        float(d.start_min),
                        float(d.duration_min),
                        d.description,
                    )
                )

        # Also support downtime from schedule if present
        if self.schedule and self.schedule.downtimes and not self.disruptions:
            for dt in self.schedule.downtimes:
                if dt.machine_id in machine_resources:
                    env.process(
                        breakdown_process(
                            dt.machine_id,
                            float(dt.start_min),
                            float(dt.duration_min),
                            dt.reason,
                        )
                    )

        # 2. Job Execution Process
        def job_process(job: Job):
            arrival = getattr(job, "arrival_min", 0)
            if arrival > env.now:
                yield env.timeout(arrival - env.now)

            log_event("JOB_ARRIVED", job_id=job.job_id, details=f"Job {job.job_id} arrived on shop floor")
            job_starts[job.job_id] = env.now

            # Iterate through ordered operations
            for op in job.operations:
                m_res = machine_resources[op.machine_id]
                base_duration = float(op.duration_min)
                if stochastic:
                    factor = 1.0 + random.uniform(-variation_pct, variation_pct)
                    actual_duration = max(1.0, round(base_duration * factor, 2))
                else:
                    actual_duration = base_duration

                # Planned start time from schedule
                p_start = planned_starts.get((job.job_id, op.operation_seq))
                if dispatch_mode == "schedule_paced" and p_start is not None and env.now < p_start:
                    yield env.timeout(p_start - env.now)

                log_event(
                    "OP_QUEUED",
                    job_id=job.job_id,
                    operation_seq=op.operation_seq,
                    machine_id=op.machine_id,
                    details=f"Waiting for machine {op.machine_id} (duration: {actual_duration:.1f}m)",
                )

                # Priority score for queueing:
                planned_score = p_start if p_start is not None else (1000 + job.priority * 100)
                urgency_bonus = -50 if getattr(job, "is_urgent", False) else 0
                priority_score = planned_score + urgency_bonus

                q_enter_time = env.now
                remaining_duration = actual_duration
                first_start_time: float | None = None

                # Loop to support resumption if interrupted by a machine breakdown
                while remaining_duration > 0:
                    with m_res.request(priority=priority_score, preempt=False) as req:
                        yield req
                        t_proc_start = env.now
                        if first_start_time is None:
                            first_start_time = t_proc_start
                            wait_time = t_proc_start - q_enter_time
                            job_wait_times[job.job_id] += wait_time
                            log_event(
                                "OP_STARTED",
                                job_id=job.job_id,
                                operation_seq=op.operation_seq,
                                machine_id=op.machine_id,
                                details=f"Started processing on {op.machine_id}",
                            )

                        try:
                            yield env.timeout(remaining_duration)
                            # Finished without interruption
                            elapsed = env.now - t_proc_start
                            machine_busy_time[op.machine_id] += elapsed
                            job_proc_times[job.job_id] += elapsed
                            remaining_duration = 0.0
                        except simpy.Interrupt as interrupt:
                            elapsed = env.now - t_proc_start
                            machine_busy_time[op.machine_id] += elapsed
                            job_proc_times[job.job_id] += elapsed
                            remaining_duration -= elapsed
                            log_event(
                                "OP_PREEMPTED",
                                job_id=job.job_id,
                                operation_seq=op.operation_seq,
                                machine_id=op.machine_id,
                                details=f"Interrupted by machine breakdown. {remaining_duration:.1f}m remaining",
                            )

                end_time = env.now
                machine_ops_count[op.machine_id] += 1
                log_event(
                    "OP_COMPLETED",
                    job_id=job.job_id,
                    operation_seq=op.operation_seq,
                    machine_id=op.machine_id,
                    details=f"Finished processing on {op.machine_id} at t={end_time:.1f}m",
                )

                op_timelines.append(
                    {
                        "job_id": job.job_id,
                        "job_name": job.job_name,
                        "operation_seq": op.operation_seq,
                        "operation_name": op.operation_name,
                        "machine_id": op.machine_id,
                        "duration_min": actual_duration,
                        "start_min": round(first_start_time or 0.0, 2),
                        "end_min": round(end_time, 2),
                        "is_urgent": getattr(job, "is_urgent", False),
                    }
                )

            job_completions[job.job_id] = env.now
            log_event(
                "JOB_COMPLETED",
                job_id=job.job_id,
                details=f"Job {job.job_id} completely manufactured at t={env.now:.1f}m",
            )

        # Launch all job processes
        for job in self.jobs:
            env.process(job_process(job))

        # Run simulation to completion
        env.run()

        makespan = max(job_completions.values()) if job_completions else 0.0

        # Compile job metrics
        job_metrics: dict[str, dict[str, Any]] = {}
        for job in self.jobs:
            c_time = job_completions.get(job.job_id, makespan)
            s_time = job_starts.get(job.job_id, 0.0)
            tardiness = max(0.0, c_time - job.due_min)
            job_metrics[job.job_id] = {
                "job_id": job.job_id,
                "job_name": job.job_name,
                "product": job.product,
                "priority": job.priority,
                "due_min": job.due_min,
                "arrival_min": getattr(job, "arrival_min", 0),
                "start_min": round(s_time, 2),
                "completion_min": round(c_time, 2),
                "duration_min": round(job_proc_times.get(job.job_id, 0.0), 2),
                "total_waiting_min": round(job_wait_times.get(job.job_id, 0.0), 2),
                "tardiness_min": round(tardiness, 2),
                "is_tardy": tardiness > 0.0,
            }

        # Compile machine metrics
        cat = machine_by_id(self.machines)
        machine_metrics: dict[str, dict[str, Any]] = {}
        for m in self.machines:
            busy = machine_busy_time[m.machine_id]
            downtime = machine_downtime[m.machine_id]
            # Machine Utilization (%) = (Busy Time / Observation Horizon) * 100
            horizon = max(makespan, 1.0)
            util_pct = (busy / horizon) * 100.0
            idle = max(0.0, horizon - busy - downtime)
            machine_metrics[m.machine_id] = {
                "machine_id": m.machine_id,
                "machine_name": cat[m.machine_id].name if m.machine_id in cat else m.machine_id,
                "busy_min": round(busy, 2),
                "idle_min": round(idle, 2),
                "downtime_min": round(downtime, 2),
                "utilization_pct": round(min(100.0, util_pct), 2),
                "operations_processed": machine_ops_count[m.machine_id],
                "breakdowns_count": machine_bd_count[m.machine_id],
            }

        notes = (
            f"Simulated {len(self.jobs)} jobs across {len(self.machines)} machines.",
            f"Execution makespan: {makespan:.1f} minutes.",
            f"Total events logged: {len(events)}.",
        )

        result = SimulationResult(
            makespan_min=round(makespan, 2),
            completed=len(job_completions) == len(self.jobs),
            notes=notes,
            events=events,
            job_metrics=job_metrics,
            machine_metrics=machine_metrics,
            operations_timeline=op_timelines,
        )

        try:
            log_simulation_result(result)
        except Exception:
            pass

        return result
