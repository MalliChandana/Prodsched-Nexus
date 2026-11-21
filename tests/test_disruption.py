"""Tests for the Disruption Center and Rescheduling in ProdSched Nexus."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_manager import Job, Operation, load_jobs, machine_catalog
from disruption import Disruption, DisruptionManager, apply_disruption
from scheduler import MachineDowntime, ScheduleError, solve_job_shop, validate_schedule


class DisruptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.jobs = load_jobs()
        self.baseline_result = solve_job_shop(self.jobs)
        self.assertEqual(self.baseline_result.makespan_min, 210)

    def test_machine_breakdown_prevents_overlap_and_delays_makespan(self) -> None:
        """Test that a breakdown on Cutting blocks the machine during the downtime interval."""
        mgr = DisruptionManager()
        # CUT is busy from 0-55 with J-103 op 1, and 55-115 with J-102 op 1
        # Add a breakdown on CUT from 50 to 90 (duration 40m)
        mgr.add_breakdown("CUT", start_min=50, duration_min=40, reason="Motor overheat")

        revised = mgr.reschedule(self.jobs)
        self.assertTrue(revised.solved)
        self.assertEqual(revised.status, "OPTIMAL")
        self.assertTrue(revised.is_disrupted)
        self.assertEqual(len(revised.downtimes), 1)

        # Baseline was 210 min. Revised must be greater due to 40 min breakdown on critical path
        self.assertGreater(revised.makespan_min, 210)

        # Verify no operation on CUT overlaps with [50, 90)
        cut_ops = [op for op in revised.operations if op.machine_id == "CUT"]
        for op in cut_ops:
            overlap = not (op.end_min <= 50 or op.start_min >= 90)
            self.assertFalse(
                overlap,
                f"Operation {op.job_id} op {op.operation_seq} [{op.start_min}, {op.end_min}) overlaps breakdown [50, 90) on CUT",
            )

        # Full validation
        validate_schedule(self.jobs, revised, breakdowns=revised.downtimes)

    def test_urgent_job_insertion(self) -> None:
        """Test inserting a high-priority urgent job."""
        urgent_job = Job(
            job_id="J-URGENT",
            job_name="Emergency Valve",
            product="Valve Body",
            quantity=1,
            priority=1,
            due_min=120,
            operations=(
                Operation("J-URGENT", 1, "Quick Cut", "CUT", 15),
                Operation("J-URGENT", 2, "Precision Drill", "DRL", 15),
            ),
            is_urgent=True,
        )

        mgr = DisruptionManager()
        mgr.add_urgent_job(urgent_job)

        revised = mgr.reschedule(self.jobs)
        self.assertTrue(revised.solved)
        # 5 original jobs + 1 urgent job = 6 jobs
        scheduled_job_ids = {op.job_id for op in revised.operations}
        self.assertIn("J-URGENT", scheduled_job_ids)
        self.assertEqual(len(scheduled_job_ids), 6)

        # Check total scheduled operations = 13 + 2 = 15
        self.assertEqual(len(revised.operations), 15)
        validate_schedule(mgr.apply_to_jobs(self.jobs), revised)

    def test_processing_delay_shifts_schedule(self) -> None:
        """Test extending an operation duration."""
        mgr = DisruptionManager()
        # Add 30 min delay to J-101 op 1 (Cutting)
        mgr.add_processing_delay("J-101", operation_seq=1, delay_min=30, reason="Hard workpiece alloy")

        revised = mgr.reschedule(self.jobs)
        self.assertTrue(revised.solved)

        # Check that J-101 op 1 has new duration = 45 + 30 = 75
        op1 = next(op for op in revised.operations if op.job_id == "J-101" and op.operation_seq == 1)
        self.assertEqual(op1.duration_min, 75)
        self.assertEqual(op1.end_min - op1.start_min, 75)

        # Comparison analysis
        comp = mgr.compare_schedules(self.baseline_result, revised, self.jobs)
        self.assertGreaterEqual(comp["revised_makespan_min"], comp["baseline_makespan_min"])
        self.assertIn("J-101", comp["job_delays"])

    def test_apply_disruption_helper(self) -> None:
        """Verify the top-level apply_disruption convenience function."""
        d = Disruption(
            disruption_id="TEST-1",
            kind="MACHINE_BREAKDOWN",
            description="Test breakdown",
            machine_id="FIN",
            start_min=10,
            duration_min=20,
        )
        revised = apply_disruption(self.baseline_result, d, base_jobs=self.jobs)
        self.assertTrue(revised.solved)
        self.assertEqual(len(revised.downtimes), 1)


if __name__ == "__main__":
    unittest.main()
