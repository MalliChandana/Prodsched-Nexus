"""Tests for SimPy Discrete-Event Simulation in ProdSched Nexus."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_manager import Job, Operation, load_jobs, machine_catalog
from disruption import Disruption
from scheduler import solve_job_shop
from simulator import WorkshopSimulator


class SimulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.jobs = load_jobs()
        self.schedule = solve_job_shop(self.jobs)
        self.machines = machine_catalog()

    def test_simulation_completes_all_jobs_and_reproduces_baseline(self) -> None:
        """Verify that standard schedule-paced simulation completes all jobs at exactly 210 min."""
        sim = WorkshopSimulator(schedule=self.schedule, jobs=self.jobs, machines=self.machines)
        result = sim.run(dispatch_mode="schedule_paced")

        self.assertTrue(result.completed)
        self.assertEqual(result.makespan_min, 210.0)
        self.assertEqual(len(result.job_metrics), 5)
        self.assertEqual(len(result.machine_metrics), 3)

        # Check that 13 operations were executed
        self.assertEqual(len(result.operations_timeline), 13)

    def test_job_precedence_respected_in_simulation(self) -> None:
        """Verify that every job's operations run sequentially without overlap."""
        sim = WorkshopSimulator(schedule=self.schedule, jobs=self.jobs)
        result = sim.run()

        # Group operations by job
        by_job: dict[str, list[dict]] = {}
        for op in result.operations_timeline:
            by_job.setdefault(op["job_id"], []).append(op)

        for job_id, ops in by_job.items():
            ops_sorted = sorted(ops, key=lambda x: x["operation_seq"])
            for prev_op, curr_op in zip(ops_sorted, ops_sorted[1:]):
                self.assertLessEqual(
                    prev_op["end_min"],
                    curr_op["start_min"],
                    f"Job {job_id} op {curr_op['operation_seq']} started at {curr_op['start_min']} before op {prev_op['operation_seq']} ended at {prev_op['end_min']}",
                )

    def test_machine_no_overlap_in_simulation(self) -> None:
        """Verify that no machine runs two operations concurrently."""
        sim = WorkshopSimulator(schedule=self.schedule, jobs=self.jobs)
        result = sim.run()

        by_mach: dict[str, list[dict]] = {}
        for op in result.operations_timeline:
            by_mach.setdefault(op["machine_id"], []).append(op)

        for mid, ops in by_mach.items():
            ops_sorted = sorted(ops, key=lambda x: x["start_min"])
            for prev_op, curr_op in zip(ops_sorted, ops_sorted[1:]):
                self.assertLessEqual(
                    prev_op["end_min"],
                    curr_op["start_min"],
                    f"Machine {mid} overlaps {prev_op['job_id']} [{prev_op['start_min']}-{prev_op['end_min']}] with {curr_op['job_id']} [{curr_op['start_min']}-{curr_op['end_min']}]",
                )

    def test_breakdown_event_preemption_and_recovery(self) -> None:
        """Verify that a breakdown in simulation preempts or delays execution and increases makespan."""
        breakdown = Disruption(
            disruption_id="SIM-BD-1",
            kind="MACHINE_BREAKDOWN",
            description="Cutting tool jam",
            machine_id="CUT",
            start_min=60,
            duration_min=45,
        )
        sim = WorkshopSimulator(
            schedule=self.schedule,
            jobs=self.jobs,
            machines=self.machines,
            disruptions=(breakdown,),
        )
        result = sim.run()

        self.assertTrue(result.completed)
        self.assertGreater(result.makespan_min, 210.0)

        # Check machine metrics for CUT
        cut_metric = result.machine_metrics["CUT"]
        self.assertEqual(cut_metric["downtime_min"], 45.0)
        self.assertEqual(cut_metric["breakdowns_count"], 1)

        # Check that BREAKDOWN_START and BREAKDOWN_END events were recorded
        event_types = [e.event_type for e in result.events]
        self.assertIn("BREAKDOWN_START", event_types)
        self.assertIn("BREAKDOWN_END", event_types)

    def test_simulation_metrics_accuracy(self) -> None:
        """Verify that busy time, waiting time, and utilization are computed accurately."""
        sim = WorkshopSimulator(schedule=self.schedule, jobs=self.jobs)
        result = sim.run(dispatch_mode="schedule_paced")
        summary = result.summary()

        # Total busy time on CUT = 45 + 60 + 55 = 160
        cut_metric = result.machine_metrics["CUT"]
        self.assertEqual(cut_metric["busy_min"], 160.0)
        # Utilization = (160 / 210) * 100 = ~76.19%
        expected_util = round((160.0 / 210.0) * 100.0, 2)
        self.assertEqual(cut_metric["utilization_pct"], expected_util)


if __name__ == "__main__":
    unittest.main()
