"""Tests for Analytics, KPI Calculations, and Reports in ProdSched Nexus."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics import (
    compute_job_metrics,
    compute_machine_metrics,
    compute_production_kpis,
    export_analytics_to_csv_string,
    export_schedule_to_csv_string,
)
from data_manager import load_jobs, machine_catalog
from scheduler import MachineDowntime, solve_job_shop


class AnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.jobs = load_jobs()
        self.machines = machine_catalog()
        self.schedule = solve_job_shop(self.jobs)

    def test_makespan_calculation(self) -> None:
        """Makespan must equal the maximum completion time across all scheduled operations."""
        max_end = max(op.end_min for op in self.schedule.operations)
        self.assertEqual(self.schedule.makespan_min, max_end)
        self.assertEqual(max_end, 210)

    def test_machine_utilization_formula(self) -> None:
        """Utilization (%) = (Busy Time / Observation Horizon) * 100."""
        horizon = self.schedule.makespan_min
        df = compute_machine_metrics(self.schedule.operations, horizon, self.machines)

        # Cutting: J-101 (45), J-102 (60), J-103 (55) => total = 160
        cut_row = df[df["machine_id"] == "CUT"].iloc[0]
        self.assertEqual(cut_row["busy_time_min"], 160)
        expected_cut_util = round((160 / 210) * 100.0, 2)
        self.assertEqual(cut_row["utilization_pct"], expected_cut_util)

        # Drilling: J-101 (30), J-102 (40), J-103 (22), J-104 (28), J-105 (36) => total = 156
        drl_row = df[df["machine_id"] == "DRL"].iloc[0]
        self.assertEqual(drl_row["busy_time_min"], 156)
        expected_drl_util = round((156 / 210) * 100.0, 2)
        self.assertEqual(drl_row["utilization_pct"], expected_drl_util)

        # Finishing: J-101 (20), J-102 (25), J-103 (35), J-104 (32), J-105 (24) => total = 136
        fin_row = df[df["machine_id"] == "FIN"].iloc[0]
        self.assertEqual(fin_row["busy_time_min"], 136)
        expected_fin_util = round((136 / 210) * 100.0, 2)
        self.assertEqual(fin_row["utilization_pct"], expected_fin_util)

    def test_downtime_reduces_idle_and_reflected_in_metrics(self) -> None:
        """When a machine has downtime, downtime_min is tracked and idle time is adjusted."""
        dt = MachineDowntime("CUT", "Cutting", 50, 40, 90, "Blown blade")
        df = compute_machine_metrics(
            self.schedule.operations,
            horizon_min=250,
            machines=self.machines,
            downtimes=(dt,),
        )
        cut_row = df[df["machine_id"] == "CUT"].iloc[0]
        self.assertEqual(cut_row["downtime_min"], 40)
        self.assertEqual(cut_row["busy_time_min"], 160)
        # 250 - 160 - 40 = 50 idle
        self.assertEqual(cut_row["idle_time_min"], 50)

    def test_job_metrics_and_tardiness(self) -> None:
        """Test calculation of job cycle times, waiting times, and tardiness."""
        df = compute_job_metrics(self.schedule.operations, self.jobs)
        self.assertEqual(len(df), 5)

        # In baseline, all jobs finish on or before due date
        # J-101: due 220, ends at 210 => on-time
        j101 = df[df["job_id"] == "J-101"].iloc[0]
        self.assertEqual(j101["completion_min"], 210)
        self.assertEqual(j101["tardiness_min"], 0)
        self.assertEqual(j101["status"], "On-Time")

        # J-101 operations are 45 (115-160), 30 (160-190), 20 (190-210) => starts at 115, ends 210 => span 95, proc 95 => wait 0
        self.assertEqual(j101["processing_min"], 95)
        self.assertEqual(j101["waiting_min"], 0)

    def test_production_kpis(self) -> None:
        """Verify the KPI dashboard summary metrics."""
        kpis = compute_production_kpis(self.schedule, self.jobs, self.machines)
        self.assertEqual(kpis["total_jobs"], 5)
        self.assertEqual(kpis["makespan_min"], 210)
        self.assertEqual(kpis["delayed_orders_count"], 0)
        self.assertEqual(kpis["total_operations"], 13)
        self.assertGreater(kpis["average_utilization_pct"], 70.0)

    def test_csv_export_formatting(self) -> None:
        """Verify CSV export strings."""
        sched_csv = export_schedule_to_csv_string(self.schedule)
        self.assertIn("job_id,job_name,operation_seq", sched_csv)
        self.assertIn("J-101", sched_csv)

        mach_df = compute_machine_metrics(self.schedule.operations, 210, self.machines)
        job_df = compute_job_metrics(self.schedule.operations, self.jobs)
        analytics_csv = export_analytics_to_csv_string(mach_df, job_df)
        self.assertIn("MACHINE UTILIZATION", analytics_csv)
        self.assertIn("JOB PERFORMANCE", analytics_csv)


if __name__ == "__main__":
    unittest.main()
