"""Performance analytics, KPI calculation, and interactive Plotly Gantt charts for ProdSched Nexus.

Calculates:
- Machine Utilization (%) = (Busy Time / Available Time) × 100
- Makespan = max(Operation Completion Times)
- Job Waiting Time = Sum of non-processing gap intervals
- Job Tardiness = max(0, Completion Time - Due Time)
- Disruption impact and before/after comparisons
"""

from __future__ import annotations

import io
from typing import Any, Sequence

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from data_manager import (
    Job,
    Machine,
    machine_by_id,
    machine_catalog,
)
from scheduler import (
    MachineDowntime,
    ScheduledOperation,
    ScheduleResult,
)

# Standard typography and color constants for crisp industrial styling
FONT_FAMILY = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
COLOR_PRIMARY_NAVY = "#0F172A"
COLOR_TEXT_MUTED = "#64748B"
COLOR_TEXT_DARK = "#1E293B"
COLOR_BG_CARD = "#FFFFFF"
COLOR_BG_PLOT = "#F8FAFC"
COLOR_BORDER = "#E2E8F0"
COLOR_GRID = "#F1F5F9"
COLOR_HOVER_BG = "#0F172A"
COLOR_HOVER_TEXT = "#FFFFFF"

JOB_PALETTE = {
    "J-101": "#2563EB",  # Industrial Cobalt Blue
    "J-102": "#0284C7",  # Sky Blue
    "J-103": "#4F46E5",  # Royal Indigo
    "J-104": "#0D9488",  # Deep Teal
    "J-105": "#D97706",  # Warm Amber
    "J-URGENT": "#DC2626",  # Crimson for rush orders
}


def compute_machine_metrics(
    operations: Sequence[ScheduledOperation],
    horizon_min: int,
    machines: Sequence[Machine] | None = None,
    downtimes: Sequence[MachineDowntime] | None = None,
) -> pd.DataFrame:
    """Compute workload, downtime, idle time, and utilization percentage for each machine."""
    cat = machine_by_id(machines)
    all_machines = machines if machines is not None else machine_catalog()
    dt_list = tuple(downtimes) if downtimes else ()

    busy_times: dict[str, int] = {m.machine_id: 0 for m in all_machines}
    ops_counts: dict[str, int] = {m.machine_id: 0 for m in all_machines}
    for op in operations:
        busy_times[op.machine_id] = busy_times.get(op.machine_id, 0) + op.duration_min
        ops_counts[op.machine_id] = ops_counts.get(op.machine_id, 0) + 1

    downtime_totals: dict[str, int] = {m.machine_id: 0 for m in all_machines}
    for dt in dt_list:
        downtime_totals[dt.machine_id] = downtime_totals.get(dt.machine_id, 0) + dt.duration_min

    observation_horizon = max(horizon_min, 1)

    rows: list[dict[str, Any]] = []
    for m in all_machines:
        mid = m.machine_id
        busy = busy_times.get(mid, 0)
        down = downtime_totals.get(mid, 0)
        idle = max(0, observation_horizon - busy - down)
        # Utilization formula: (Busy Time / Observation Horizon) * 100
        util_pct = (busy / observation_horizon) * 100.0

        rows.append(
            {
                "machine_id": mid,
                "machine_name": m.name,
                "busy_time_min": busy,
                "downtime_min": down,
                "idle_time_min": idle,
                "utilization_pct": round(min(100.0, util_pct), 2),
                "operations_count": ops_counts.get(mid, 0),
                "operational_status": m.status,
            }
        )

    return pd.DataFrame(rows)


def compute_job_metrics(
    operations: Sequence[ScheduledOperation],
    jobs: Sequence[Job],
) -> pd.DataFrame:
    """Calculate start times, completion times, waiting times, and tardiness for each job."""
    jobs_by_id = {j.job_id: j for j in jobs}
    ops_by_job: dict[str, list[ScheduledOperation]] = {}
    for op in operations:
        ops_by_job.setdefault(op.job_id, []).append(op)

    rows: list[dict[str, Any]] = []
    for jid, job in jobs_by_id.items():
        job_ops = ops_by_job.get(jid, [])
        if not job_ops:
            continue
        ordered = sorted(job_ops, key=lambda x: x.operation_seq)
        first_start = ordered[0].start_min
        completion = max(op.end_min for op in ordered)
        processing_time = sum(op.duration_min for op in ordered)
        timespan = completion - first_start
        waiting_time = max(0, timespan - processing_time)
        tardiness = max(0, completion - job.due_min)
        status = "Delayed" if tardiness > 0 else "On-Time"

        rows.append(
            {
                "job_id": jid,
                "job_name": job.job_name,
                "product": job.product,
                "quantity": job.quantity,
                "priority": job.priority,
                "due_min": job.due_min,
                "start_min": first_start,
                "completion_min": completion,
                "processing_min": processing_time,
                "waiting_min": waiting_time,
                "tardiness_min": tardiness,
                "status": status,
                "is_urgent": getattr(job, "is_urgent", False),
            }
        )

    return pd.DataFrame(rows)


def compute_production_kpis(
    schedule: ScheduleResult,
    jobs: Sequence[Job],
    machines: Sequence[Machine] | None = None,
    current_time_min: int | None = None,
) -> dict[str, Any]:
    """Compute comprehensive production workshop KPIs."""
    machs = machines if machines is not None else machine_catalog()
    makespan = schedule.makespan_min or 0
    now_t = current_time_min if current_time_min is not None else makespan

    job_df = compute_job_metrics(schedule.operations, jobs)
    mach_df = compute_machine_metrics(schedule.operations, makespan, machs, schedule.downtimes)

    total_jobs = len(jobs)
    completed_jobs = int((job_df["completion_min"] <= now_t).sum()) if not job_df.empty else 0
    in_production_jobs = (
        int(((job_df["start_min"] <= now_t) & (job_df["completion_min"] > now_t)).sum())
        if not job_df.empty
        else 0
    )
    pending_jobs = max(0, total_jobs - completed_jobs - in_production_jobs)

    delayed_orders = int((job_df["tardiness_min"] > 0).sum()) if not job_df.empty else 0
    avg_util = float(mach_df["utilization_pct"].mean()) if not mach_df.empty else 0.0
    total_downtime = int(mach_df["downtime_min"].sum()) if not mach_df.empty else 0
    total_waiting = int(job_df["waiting_min"].sum()) if not job_df.empty else 0

    return {
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "in_production_jobs": in_production_jobs,
        "pending_jobs": pending_jobs,
        "makespan_min": makespan,
        "average_utilization_pct": round(avg_util, 2),
        "total_downtime_min": total_downtime,
        "delayed_orders_count": delayed_orders,
        "total_waiting_time_min": total_waiting,
        "total_operations": len(schedule.operations),
        "solver_status": schedule.status,
        "solver_wall_time_s": round(schedule.wall_time_s, 4),
    }


def create_gantt_chart(
    schedule: ScheduleResult,
    jobs: Sequence[Job] | None = None,
    machines: Sequence[Machine] | None = None,
    title: str = "Workshop Production Schedule (Gantt Chart)",
) -> go.Figure:
    """Generate an interactive Plotly horizontal bar Gantt chart showing operations and downtime."""
    cat = machine_by_id(machines)
    mach_list = machines if machines is not None else machine_catalog()
    job_map = {j.job_id: j for j in jobs} if jobs else {}

    fig = go.Figure()
    fallback_palette = px.colors.qualitative.Plotly

    # Add scheduled operations as horizontal bars
    for op in schedule.operations:
        job = job_map.get(op.job_id)
        is_urg = op.is_urgent or (job and getattr(job, "is_urgent", False))
        color = "#DC2626" if is_urg else JOB_PALETTE.get(op.job_id, fallback_palette[hash(op.job_id) % len(fallback_palette)])

        due = job.due_min if job else "-"
        status = "Tardy Risk" if (job and op.end_min > job.due_min) else "Normal Schedule"
        if is_urg:
            status = "URGENT ORDER"

        hover_text = (
            f"<b>{op.job_name} ({op.job_id})</b><br>"
            f"Operation {op.operation_seq}: {op.operation_name}<br>"
            f"Workstation: {op.machine_name} ({op.machine_id})<br>"
            f"Scheduled: {op.start_min}m → {op.end_min}m (Duration: {op.duration_min} min)<br>"
            f"Promised Due: {due} min<br>"
            f"Order Status: {status}"
        )

        fig.add_trace(
            go.Bar(
                name=f"{op.job_id}: {op.job_name}",
                y=[op.machine_name],
                x=[op.duration_min],
                base=[op.start_min],
                orientation="h",
                marker=dict(
                    color=color,
                    line=dict(color="#FFFFFF", width=1.5),
                ),
                text=f"{op.job_id} · Op {op.operation_seq}",
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(color="#FFFFFF", size=11, family=FONT_FAMILY),
                hovertext=hover_text,
                hoverinfo="text",
                showlegend=False,
            )
        )

    # Add machine breakdown intervals
    if schedule.downtimes:
        for dt in schedule.downtimes:
            hover_dt = (
                f"<b>UNPLANNED BREAKDOWN</b><br>"
                f"Machine: {dt.machine_name} ({dt.machine_id})<br>"
                f"Downtime: {dt.start_min}m → {dt.end_min}m ({dt.duration_min} min)<br>"
                f"Reason: {dt.reason}"
            )
            fig.add_trace(
                go.Bar(
                    name=f"Downtime: {dt.machine_id}",
                    y=[dt.machine_name],
                    x=[dt.duration_min],
                    base=[dt.start_min],
                    orientation="h",
                    marker=dict(
                        color="#EF4444",
                        pattern_shape="/",
                        line=dict(color="#B91C1C", width=2),
                    ),
                    text=f"BREAKDOWN ({dt.duration_min}m)",
                    textposition="inside",
                    textfont=dict(color="#FFFFFF", size=10, family=FONT_FAMILY),
                    hovertext=hover_dt,
                    hoverinfo="text",
                    showlegend=False,
                )
            )

    fig.update_layout(
        title=dict(
            text=f"<b>{title}</b>",
            font=dict(size=14, color=COLOR_PRIMARY_NAVY, family=FONT_FAMILY),
            x=0.01,
            y=0.96,
        ),
        xaxis=dict(
            title=dict(text="Timeline (Minutes from Shift Start)", font=dict(family=FONT_FAMILY, size=11, color=COLOR_TEXT_MUTED)),
            gridcolor=COLOR_GRID,
            showgrid=True,
            zeroline=True,
            zerolinecolor=COLOR_BORDER,
            tickfont=dict(family=FONT_FAMILY, size=11, color=COLOR_TEXT_MUTED),
            rangemode="tozero",
        ),
        yaxis=dict(
            title=dict(text="", font=dict(family=FONT_FAMILY, size=11)),
            gridcolor=COLOR_GRID,
            tickfont=dict(family=FONT_FAMILY, size=12, color=COLOR_PRIMARY_NAVY),
            autorange="reversed",
        ),
        barmode="overlay",
        plot_bgcolor=COLOR_BG_PLOT,
        paper_bgcolor=COLOR_BG_CARD,
        margin=dict(l=75, r=30, t=45, b=45),
        height=320,
        hoverlabel=dict(bgcolor=COLOR_HOVER_BG, font_color=COLOR_HOVER_TEXT, font_family=FONT_FAMILY, font_size=12),
    )

    return fig


def create_comparison_gantt(
    baseline: ScheduleResult,
    revised: ScheduleResult,
    jobs: Sequence[Job] | None = None,
) -> go.Figure:
    """Stacked subplots comparing Baseline Timetable vs Revised Timetable."""
    delta = (revised.makespan_min or 0) - (baseline.makespan_min or 0)
    delta_str = f"+{delta} min" if delta > 0 else (f"{delta} min" if delta < 0 else "0 min")

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        subplot_titles=(
            f"Baseline Schedule (Optimal Makespan: {baseline.makespan_min} min)",
            f"Revised Schedule with Disruptions (Makespan: {revised.makespan_min} min · Δ: {delta_str})",
        ),
        vertical_spacing=0.14,
    )

    # Baseline bars
    for op in baseline.operations:
        color = JOB_PALETTE.get(op.job_id, "#4B5563")
        fig.add_trace(
            go.Bar(
                y=[op.machine_name],
                x=[op.duration_min],
                base=[op.start_min],
                orientation="h",
                marker=dict(color=color, line=dict(color="#FFFFFF", width=1.2)),
                text=f"{op.job_id} · Op {op.operation_seq}",
                textposition="inside",
                hovertext=f"Baseline: {op.job_id} ({op.start_min}-{op.end_min}m)",
                hoverinfo="text",
                showlegend=False,
            ),
            row=1,
            col=1,
        )

    # Revised bars
    for op in revised.operations:
        is_urg = op.is_urgent
        color = "#DC2626" if is_urg else JOB_PALETTE.get(op.job_id, "#4B5563")
        fig.add_trace(
            go.Bar(
                y=[op.machine_name],
                x=[op.duration_min],
                base=[op.start_min],
                orientation="h",
                marker=dict(color=color, line=dict(color="#FFFFFF", width=1.2)),
                text=f"{op.job_id} · Op {op.operation_seq}",
                textposition="inside",
                hovertext=f"Revised: {op.job_id} ({op.start_min}-{op.end_min}m)",
                hoverinfo="text",
                showlegend=False,
            ),
            row=2,
            col=1,
        )

    # Revised downtimes
    if revised.downtimes:
        for dt in revised.downtimes:
            fig.add_trace(
                go.Bar(
                    y=[dt.machine_name],
                    x=[dt.duration_min],
                    base=[dt.start_min],
                    orientation="h",
                    marker=dict(color="#EF4444", pattern_shape="/", line=dict(color="#B91C1C", width=1.5)),
                    text=f"BREAKDOWN ({dt.duration_min}m)",
                    textposition="inside",
                    hovertext=f"Breakdown: {dt.machine_name} {dt.start_min}-{dt.end_min}m ({dt.reason})",
                    hoverinfo="text",
                    showlegend=False,
                ),
                row=2,
                col=1,
            )

    fig.update_layout(
        height=520,
        barmode="overlay",
        plot_bgcolor=COLOR_BG_PLOT,
        paper_bgcolor=COLOR_BG_CARD,
        margin=dict(l=75, r=30, t=50, b=45),
        hoverlabel=dict(bgcolor=COLOR_HOVER_BG, font_color=COLOR_HOVER_TEXT, font_family=FONT_FAMILY, font_size=12),
    )
    fig.update_yaxes(autorange="reversed", tickfont=dict(family=FONT_FAMILY, size=11, color=COLOR_PRIMARY_NAVY), gridcolor=COLOR_GRID)
    fig.update_xaxes(
        title_text="Timeline (Minutes)",
        title_font=dict(family=FONT_FAMILY, size=11, color=COLOR_TEXT_MUTED),
        tickfont=dict(family=FONT_FAMILY, size=11, color=COLOR_TEXT_MUTED),
        gridcolor=COLOR_GRID,
        row=2,
        col=1,
    )

    return fig


def create_utilization_bar_chart(mach_df: pd.DataFrame) -> go.Figure:
    """Create a clean stacked bar chart showing machine busy time, downtime, and idle time."""
    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            name="Busy Time",
            x=mach_df["machine_name"],
            y=mach_df["busy_time_min"],
            marker_color="#2563EB",
            text=mach_df["busy_time_min"].apply(lambda v: f"{v}m"),
            textposition="inside",
            textfont=dict(family=FONT_FAMILY, size=11, color="#FFFFFF"),
        )
    )
    fig.add_trace(
        go.Bar(
            name="Downtime",
            x=mach_df["machine_name"],
            y=mach_df["downtime_min"],
            marker_color="#EF4444",
            text=mach_df["downtime_min"].apply(lambda v: f"{v}m" if v > 0 else ""),
            textposition="inside",
            textfont=dict(family=FONT_FAMILY, size=11, color="#FFFFFF"),
        )
    )
    fig.add_trace(
        go.Bar(
            name="Idle Time",
            x=mach_df["machine_name"],
            y=mach_df["idle_time_min"],
            marker_color="#94A3B8",
            text=mach_df["idle_time_min"].apply(lambda v: f"{v}m"),
            textposition="inside",
            textfont=dict(family=FONT_FAMILY, size=11, color="#FFFFFF"),
        )
    )

    fig.update_layout(
        barmode="stack",
        title=dict(text="<b>Workstation Time Allocation (Busy vs Downtime vs Idle)</b>", font=dict(family=FONT_FAMILY, size=13, color=COLOR_PRIMARY_NAVY)),
        plot_bgcolor=COLOR_BG_PLOT,
        paper_bgcolor=COLOR_BG_CARD,
        xaxis=dict(title="", tickfont=dict(family=FONT_FAMILY, size=11, color=COLOR_PRIMARY_NAVY), gridcolor=COLOR_GRID),
        yaxis=dict(title="Minutes", title_font=dict(family=FONT_FAMILY, size=11, color=COLOR_TEXT_MUTED), tickfont=dict(family=FONT_FAMILY, size=11, color=COLOR_TEXT_MUTED), gridcolor=COLOR_GRID),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(family=FONT_FAMILY, size=11)),
        height=300,
        margin=dict(l=50, r=20, t=45, b=35),
        hoverlabel=dict(bgcolor=COLOR_HOVER_BG, font_color=COLOR_HOVER_TEXT, font_family=FONT_FAMILY, font_size=12),
    )
    return fig


def create_waiting_time_chart(job_df: pd.DataFrame) -> go.Figure:
    """Horizontal stacked bar comparing processing vs waiting time by job."""
    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            name="Active Processing",
            y=job_df["job_id"],
            x=job_df["processing_min"],
            orientation="h",
            marker_color="#0D9488",
            text=job_df["processing_min"].apply(lambda v: f"{v}m"),
            textposition="inside",
            textfont=dict(family=FONT_FAMILY, size=11, color="#FFFFFF"),
        )
    )
    fig.add_trace(
        go.Bar(
            name="In-Queue Waiting",
            y=job_df["job_id"],
            x=job_df["waiting_min"],
            orientation="h",
            marker_color="#F59E0B",
            text=job_df["waiting_min"].apply(lambda v: f"{v}m" if v > 0 else ""),
            textposition="inside",
            textfont=dict(family=FONT_FAMILY, size=11, color="#FFFFFF"),
        )
    )

    fig.update_layout(
        barmode="stack",
        title=dict(text="<b>Job Cycle Time Breakdown (Processing vs Queue Wait)</b>", font=dict(family=FONT_FAMILY, size=13, color=COLOR_PRIMARY_NAVY)),
        plot_bgcolor=COLOR_BG_PLOT,
        paper_bgcolor=COLOR_BG_CARD,
        xaxis=dict(title="Duration (Minutes)", title_font=dict(family=FONT_FAMILY, size=11, color=COLOR_TEXT_MUTED), tickfont=dict(family=FONT_FAMILY, size=11, color=COLOR_TEXT_MUTED), gridcolor=COLOR_GRID),
        yaxis=dict(title="", tickfont=dict(family=FONT_FAMILY, size=11, color=COLOR_PRIMARY_NAVY), autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(family=FONT_FAMILY, size=11)),
        height=300,
        margin=dict(l=55, r=20, t=45, b=35),
        hoverlabel=dict(bgcolor=COLOR_HOVER_BG, font_color=COLOR_HOVER_TEXT, font_family=FONT_FAMILY, font_size=12),
    )
    return fig


def create_tardiness_chart(job_df: pd.DataFrame) -> go.Figure:
    """Compare Job Completion vs Delivery Deadline."""
    fig = go.Figure()

    colors = job_df["status"].apply(lambda s: "#EF4444" if s == "Delayed" else "#2563EB")
    fig.add_trace(
        go.Bar(
            name="Completion Time",
            x=job_df["job_id"],
            y=job_df["completion_min"],
            marker_color=colors,
            text=job_df["completion_min"].apply(lambda v: f"{v}m"),
            textposition="inside",
            textfont=dict(family=FONT_FAMILY, size=11, color="#FFFFFF"),
        )
    )
    fig.add_trace(
        go.Scatter(
            name="Promised Deadline",
            x=job_df["job_id"],
            y=job_df["due_min"],
            mode="lines+markers",
            marker=dict(color="#DC2626", size=8, symbol="diamond"),
            line=dict(color="#DC2626", width=2, dash="dash"),
        )
    )

    fig.update_layout(
        title=dict(text="<b>Order Completion vs Promised Delivery Deadline</b>", font=dict(family=FONT_FAMILY, size=13, color=COLOR_PRIMARY_NAVY)),
        plot_bgcolor=COLOR_BG_PLOT,
        paper_bgcolor=COLOR_BG_CARD,
        xaxis=dict(title="", tickfont=dict(family=FONT_FAMILY, size=11, color=COLOR_PRIMARY_NAVY), gridcolor=COLOR_GRID),
        yaxis=dict(title="Minutes", title_font=dict(family=FONT_FAMILY, size=11, color=COLOR_TEXT_MUTED), tickfont=dict(family=FONT_FAMILY, size=11, color=COLOR_TEXT_MUTED), gridcolor=COLOR_GRID),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(family=FONT_FAMILY, size=11)),
        height=300,
        margin=dict(l=50, r=20, t=45, b=35),
        hoverlabel=dict(bgcolor=COLOR_HOVER_BG, font_color=COLOR_HOVER_TEXT, font_family=FONT_FAMILY, font_size=12),
    )
    return fig


def export_schedule_to_csv_string(schedule: ScheduleResult) -> str:
    """Convert schedule result to downloadable CSV string."""
    df = schedule.to_dataframe()
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue()


def export_analytics_to_csv_string(mach_df: pd.DataFrame, job_df: pd.DataFrame) -> str:
    """Combine machine and job analytics into a formatted CSV report string."""
    buffer = io.StringIO()
    buffer.write("=== PRODSCHED NEXUS: WORKSHOP PERFORMANCE REPORT ===\n")
    buffer.write("=== MACHINE UTILIZATION AND WORKLOAD ===\n")
    mach_df.to_csv(buffer, index=False)
    buffer.write("\n=== JOB PERFORMANCE: LEAD TIMES AND DELIVERY  ===\n")
    job_df.to_csv(buffer, index=False)
    return buffer.getvalue()
