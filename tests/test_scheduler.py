"""Checks for the sample workshop and the CP-SAT job-shop engine."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_manager import Job, Machine, Operation, load_jobs, machine_catalog
from scheduler import (
    SOLVER_NAME,
    build_job_shop_model,
    lower_bound_min,
    solve_job_shop,
    validate_schedule,
)


class SampleDataTests(unittest.TestCase):
    def test_catalogue_and_sample_jobs(self) -> None:
        machines = machine_catalog()
        self.assertEqual([machine.name for machine in machines], ["Cutting", "Drilling", "Finishing"])

        jobs = load_jobs()
        self.assertEqual(len(jobs), 5)
        self.assertEqual([job.job_id for job in jobs], ["J-101", "J-102", "J-103", "J-104", "J-105"])
        self.assertEqual(sum(len(job.operations) for job in jobs), 13)

        routes = {
            job.job_id: tuple(operation.machine_id for operation in job.operations)
            for job in jobs
        }
        self.assertEqual(routes["J-101"], ("CUT", "DRL", "FIN"))
        self.assertEqual(routes["J-103"], ("CUT", "FIN", "DRL"))
        self.assertEqual(routes["J-104"], ("DRL", "FIN"))
        self.assertEqual(routes["J-105"], ("FIN", "DRL"))
        self.assertNotIn("CUT", routes["J-104"])
        self.assertNotIn("CUT", routes["J-105"])


class ModelTests(unittest.TestCase):
    def test_model_posts_precedence_no_overlap_and_makespan(self) -> None:
        jobs = load_jobs()
        compiled = build_job_shop_model(jobs)
        proto = compiled.model.Proto()

        constraints = list(proto.constraints)
        used_machines = {operation.machine_id for job in jobs for operation in job.operations}
        precedence_count = sum(len(job.operations) - 1 for job in jobs)
        self.assertEqual(sum(item.has_no_overlap() for item in constraints), len(used_machines))
        self.assertEqual(sum(item.has_interval() for item in constraints), 13)
        # One precedence inequality per consecutive pair, plus makespan >= each job end.
        self.assertEqual(
            sum(item.has_linear() for item in constraints),
            precedence_count + len(jobs),
        )
        self.assertEqual(compiled.machines_with_work, ("CUT", "DRL", "FIN"))
        self.assertEqual(len(compiled.starts), 13)
        self.assertEqual(len(compiled.ends), 13)
        self.assertEqual(list(proto.objective.vars), [compiled.makespan.Index()])
        self.assertEqual(list(proto.objective.coeffs), [1])
        self.assertEqual(proto.objective.scaling_factor, 1.0)


class ScheduleTests(unittest.TestCase):
    def test_sample_schedule_is_proven_and_feasible(self) -> None:
        jobs = load_jobs()
        result = solve_job_shop(jobs)

        self.assertEqual(result.solver, SOLVER_NAME)
        self.assertEqual(result.status, "OPTIMAL")
        self.assertIsNotNone(result.makespan_min)
        self.assertEqual(result.makespan_min, result.best_bound_min)
        self.assertGreaterEqual(result.makespan_min, lower_bound_min(jobs))
        self.assertLessEqual(result.makespan_min, result.horizon_min)
        validate_schedule(jobs, result)
        self.assert_no_overlap_and_precedence(jobs, result)

    def test_known_instance_makespan(self) -> None:
        machines = (
            Machine("A", "Machine A", "test"),
            Machine("B", "Machine B", "test"),
        )
        jobs = (
            Job(
                "T1",
                "Tiny 1",
                "test",
                1,
                1,
                100,
                (
                    Operation("T1", 1, "A first", "A", 3),
                    Operation("T1", 2, "B second", "B", 2),
                ),
            ),
            Job(
                "T2",
                "Tiny 2",
                "test",
                1,
                1,
                100,
                (
                    Operation("T2", 1, "A first", "A", 2),
                    Operation("T2", 2, "B second", "B", 1),
                ),
            ),
        )
        result = solve_job_shop(jobs, machines=machines)
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.makespan_min, 6)
        validate_schedule(jobs, result)

    def test_longer_operation_cannot_keep_the_old_makespan(self) -> None:
        jobs = list(load_jobs())
        target = jobs[0]
        stretched = Job(
            target.job_id,
            target.job_name,
            target.product,
            target.quantity,
            target.priority,
            target.due_min,
            tuple(
                Operation(
                    operation.job_id,
                    operation.operation_seq,
                    operation.operation_name,
                    operation.machine_id,
                    10_000 if operation.operation_seq == 1 else operation.duration_min,
                )
                for operation in target.operations
            ),
        )
        jobs[0] = stretched
        result = solve_job_shop(jobs)
        self.assertEqual(result.status, "OPTIMAL")
        self.assertGreaterEqual(result.makespan_min, 10_000)
        validate_schedule(jobs, result)

    def assert_no_overlap_and_precedence(self, jobs, result) -> None:
        by_machine: dict[str, list] = {}
        by_job: dict[str, list] = {}
        for operation in result.operations:
            self.assertEqual(operation.end_min - operation.start_min, operation.duration_min)
            by_machine.setdefault(operation.machine_id, []).append(operation)
            by_job.setdefault(operation.job_id, []).append(operation)

        for items in by_machine.values():
            ordered = sorted(items, key=lambda item: item.start_min)
            for previous, current in zip(ordered, ordered[1:]):
                self.assertLessEqual(previous.end_min, current.start_min)

        expected_order = {
            job.job_id: [operation.operation_seq for operation in job.operations]
            for job in jobs
        }
        for job_id, items in by_job.items():
            ordered = sorted(items, key=lambda item: item.operation_seq)
            self.assertEqual([item.operation_seq for item in ordered], expected_order[job_id])
            for previous, current in zip(ordered, ordered[1:]):
                self.assertLessEqual(previous.end_min, current.start_min)


if __name__ == "__main__":
    unittest.main()
