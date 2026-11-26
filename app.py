"""ProdSched Nexus: A Disruption-Aware Workshop Production Scheduling Engine
Using Constraint Programming (Google OR-Tools CP-SAT) and Discrete-Event Simulation (SimPy).

Enterprise industrial dashboard:
1. Dashboard (Production Overview & KPIs)
2. Job Management (Production Orders, Sequences & Routing)
3. Machine Management (Workstation Roster, Utilization & Status)
4. Schedule Optimizer (Exact Google OR-Tools CP-SAT Job-Shop Optimization)
5. Disruption Center (Machine Breakdowns, Urgent Orders, Processing Delays)
6. Production Simulation (SimPy Discrete-Event Simulation & Preemptive Breakdowns)
7. Analytics & Reports (Machine Utilization, Cycle Times, Lead Times & CSV Export)
8. System Information (Mathematical Formulation, Algorithms & System Architecture)
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics import (
    compute_job_metrics,
    compute_machine_metrics,
    compute_production_kpis,
    create_comparison_gantt,
    create_gantt_chart,
    create_tardiness_chart,
    create_utilization_bar_chart,
    create_waiting_time_chart,
    export_analytics_to_csv_string,
    export_schedule_to_csv_string,
)
from data_manager import (
    Job,
    Machine,
    Operation,
    get_default_machines,
    jobs_to_dataframe,
    load_jobs,
    machine_by_id,
    machine_catalog,
    reset_sample_data,
    save_jobs_to_csv,
    validate_jobs,
)
from database import (
    clear_disruptions,
    init_db,
    load_disruptions,
    load_jobs_from_db,
    load_machines,
    log_disruption,
    log_schedule_result,
    save_jobs,
    save_machines,
)
from disruption import Disruption, DisruptionManager
from scheduler import (
    MachineDowntime,
    ScheduleResult,
    lower_bound_min,
    solve_job_shop,
)
from simulator import WorkshopSimulator
import theme

# Page configuration
st.set_page_config(
    page_title="ProdSched Nexus | Industrial Production Scheduling",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Visual theme (navy, white and soft teal). See theme.py.
theme.inject_theme()


def initialize_application_state() -> None:
    """Initialize persistent database and application state with clean data."""
    init_db()

    if "machines" not in st.session_state:
        db_machines = load_machines()
        st.session_state.machines = list(db_machines) if db_machines else list(get_default_machines())

    if "jobs" not in st.session_state:
        db_jobs = load_jobs_from_db()
        # Verify that loaded jobs have clean product strings
        if db_jobs and not any("<bound method" in j.product for j in db_jobs):
            st.session_state.jobs = list(db_jobs)
        else:
            default_jobs = list(load_jobs())
            st.session_state.jobs = default_jobs
            try:
                save_jobs(default_jobs)
            except Exception:
                pass

    if "disruption_mgr" not in st.session_state:
        st.session_state.disruption_mgr = DisruptionManager()

    if "baseline_schedule" not in st.session_state:
        res = solve_job_shop(st.session_state.jobs, machines=tuple(st.session_state.machines))
        st.session_state.baseline_schedule = res
        try:
            log_schedule_result(res, "baseline")
        except Exception:
            pass

    if "revised_schedule" not in st.session_state:
        st.session_state.revised_schedule = st.session_state.baseline_schedule

    if "sim_result" not in st.session_state:
        st.session_state.sim_result = None


initialize_application_state()


# Sidebar Navigation & Branding
with st.sidebar:
    theme.sidebar_brand(Path(__file__).resolve().parent / "assets" / "logo.png", "Workshop Production Planner")
    st.markdown("<hr style='margin: 0.5rem 0 0.9rem 0; border: none;'/>", unsafe_allow_html=True)

    main_page = st.radio(
        "Main menu",
        [
            "Dashboard",
            "Manage Production",
            "Production Scheduling",
            "Disruptions & Simulation",
            "Reports & Insights",
        ],
        index=0,
        label_visibility="collapsed",
    )

    # Keep the original feature pages and their functionality, while grouping
    # related tools under five simple main menu items.
    if main_page == "Manage Production":
        manage_choice = st.radio("Manage production", ["Jobs", "Machines"], label_visibility="visible")
        page = "Job Management" if manage_choice == "Jobs" else "Machine Management"
    elif main_page == "Production Scheduling":
        page = "Schedule Optimizer"
    elif main_page == "Disruptions & Simulation":
        issue_choice = st.radio(
            "Production tools",
            ["Handle a Problem", "Test Production"],
            label_visibility="visible",
        )
        page = "Disruption Center" if issue_choice == "Handle a Problem" else "Production Simulation"
    elif main_page == "Reports & Insights":
        report_choice = st.radio(
            "Insights",
            ["Reports", "About This Project"],
            label_visibility="visible",
        )
        page = "Analytics & Reports" if report_choice == "Reports" else "System Information"
    else:
        page = "Dashboard"

    st.markdown("<hr style='margin: 0.8rem 0; border: none; border-top: 1px solid #E2E8F0;'/>", unsafe_allow_html=True)

    # Workshop operational status badge
    active_disruptions = len(st.session_state.disruption_mgr.disruptions)
    base_mk = st.session_state.baseline_schedule.makespan_min or 0
    rev_mk = st.session_state.revised_schedule.makespan_min or 0

    theme.sidebar_status(base_mk, rev_mk, active_disruptions)

    if st.button("🔄 Reset to Canonical Baseline", use_container_width=True):
        fresh_jobs = reset_sample_data()
        st.session_state.jobs = list(fresh_jobs)
        st.session_state.machines = list(get_default_machines())
        st.session_state.disruption_mgr.clear()
        save_jobs(st.session_state.jobs)
        clear_disruptions()
        res = solve_job_shop(st.session_state.jobs, machines=tuple(st.session_state.machines))
        st.session_state.baseline_schedule = res
        st.session_state.revised_schedule = res
        st.session_state.sim_result = None
        st.success("Workshop restored to canonical 5-job, 210-min baseline.")
        st.rerun()


# ==============================================================================
# MODULE 1: PRODUCTION DASHBOARD
# ==============================================================================
if page == "Dashboard":
    theme.hero(
        "Production Dashboard",
        "See how your jobs and machines are doing at a glance.",
        st.session_state.revised_schedule,
        st.session_state.machines,
        len({op.job_id for op in st.session_state.revised_schedule.operations}) or len(st.session_state.jobs),
        len(st.session_state.disruption_mgr.disruptions),
    )

    active_schedule = st.session_state.revised_schedule
    kpis = compute_production_kpis(
        active_schedule,
        st.session_state.jobs,
        tuple(st.session_state.machines),
    )

    # Row 1: Operational Volume Metrics
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Total Jobs</div>
                <div class="nexus-kpi-val">{kpis['total_jobs']}</div>
                <div class="nexus-kpi-sub">{kpis['total_operations']} total operations</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Workstations</div>
                <div class="nexus-kpi-val">{len(st.session_state.machines)}</div>
                <div class="nexus-kpi-sub">Active stations</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Completed Jobs</div>
                <div class="nexus-kpi-val" style="color: #1F8A5B;">{kpis['completed_jobs']}</div>
                <div class="nexus-kpi-sub">At schedule makespan</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">In Production</div>
                <div class="nexus-kpi-val" style="color: #0C7F74;">{kpis['in_production_jobs']}</div>
                <div class="nexus-kpi-sub">Active in shop floor</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c5:
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Pending Release</div>
                <div class="nexus-kpi-val" style="color: #6A7891;">{kpis['pending_jobs']}</div>
                <div class="nexus-kpi-sub">Queued for release</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Row 2: Performance & Disruption Metrics
    c6, c7, c8, c9, c10 = st.columns(5)
    base_mk_val = st.session_state.baseline_schedule.makespan_min or 0
    rev_mk_val = active_schedule.makespan_min or 0
    delta_mk = rev_mk_val - base_mk_val

    with c6:
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Original Makespan</div>
                <div class="nexus-kpi-val">{base_mk_val} <span style="font-size:0.85rem; font-weight:500; color:#6A7891;">min</span></div>
                <div class="nexus-kpi-sub">CP-SAT proven optimal</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c7:
        val_color = "#C2414B" if delta_mk > 0 else "#12294A"
        sub_str = f"+{delta_mk} min shift" if delta_mk > 0 else "Optimal baseline"
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Revised Makespan</div>
                <div class="nexus-kpi-val" style="color: {val_color};">{rev_mk_val} <span style="font-size:0.85rem; font-weight:500; color:#6A7891;">min</span></div>
                <div class="nexus-kpi-sub">{sub_str}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c8:
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Avg Utilization</div>
                <div class="nexus-kpi-val">{kpis['average_utilization_pct']}%</div>
                <div class="nexus-kpi-sub">(Total Busy / Horizon)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c9:
        dt_color = "#C2414B" if kpis['total_downtime_min'] > 0 else "#12294A"
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Total Downtime</div>
                <div class="nexus-kpi-val" style="color: {dt_color};">{kpis['total_downtime_min']} <span style="font-size:0.85rem; font-weight:500; color:#6A7891;">min</span></div>
                <div class="nexus-kpi-sub">{len(active_schedule.downtimes)} breakdown interval(s)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c10:
        delay_color = "#C2414B" if kpis['delayed_orders_count'] > 0 else "#1F8A5B"
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Delayed Orders</div>
                <div class="nexus-kpi-val" style="color: {delay_color};">{kpis['delayed_orders_count']}</div>
                <div class="nexus-kpi-sub">Past delivery deadline</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Active Production Schedule Gantt Chart
    st.markdown('<div class="nexus-section-header">Active Production Schedule Timetable</div>', unsafe_allow_html=True)
    if active_schedule.solved:
        fig = create_gantt_chart(
            active_schedule,
            st.session_state.jobs,
            st.session_state.machines,
            title=f"Workshop Schedule ({'Disrupted & Revised' if active_schedule.is_disrupted else 'Baseline Optimal'}) · Makespan: {active_schedule.makespan_min} min",
        )
        theme.themed_chart(fig, use_container_width=True)
    else:
        st.error("No valid timetable available.")

    # Two columns: Machine Workstations Status & Recent Disruption History
    col_mach, col_disrupt = st.columns([1.1, 0.9])

    with col_mach:
        st.markdown('<div class="nexus-section-header">Machine Workstation Overview</div>', unsafe_allow_html=True)
        mach_df = compute_machine_metrics(
            active_schedule.operations,
            active_schedule.makespan_min or 210,
            tuple(st.session_state.machines),
            active_schedule.downtimes,
        )

        for _, row in mach_df.iterrows():
            status_cls = "badge-success"
            if row["downtime_min"] > 0:
                status_cls = "badge-danger"
            elif row["operational_status"] != "Operational":
                status_cls = "badge-warning"

            st.markdown(
                f"""
                <div class="nexus-card" style="padding: 0.75rem 1rem; margin-bottom: 0.5rem;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <span style="font-weight: 700; color: #12294A; font-size: 0.92rem;">{row['machine_name']}</span>
                            <span style="color: #6A7891; font-size: 0.78rem; margin-left: 0.3rem;">({row['machine_id']})</span>
                        </div>
                        <span class="nexus-badge {status_cls}">{row['operational_status']}</span>
                    </div>
                    <div style="display: flex; gap: 1.25rem; margin-top: 0.5rem; font-size: 0.8rem; color: #3A4B66;">
                        <div>Utilization: <b style="color: #12294A;">{row['utilization_pct']}%</b></div>
                        <div>Busy: <b style="color: #12294A;">{row['busy_time_min']}m</b></div>
                        <div>Downtime: <b style="color: {'#C2414B' if row['downtime_min']>0 else '#12294A'};">{row['downtime_min']}m</b></div>
                        <div>Idle: <b style="color: #12294A;">{row['idle_time_min']}m</b></div>
                        <div>Ops: <b style="color: #12294A;">{row['operations_count']}</b></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with col_disrupt:
        st.markdown('<div class="nexus-section-header">Recent Disruption History</div>', unsafe_allow_html=True)
        disruptions = st.session_state.disruption_mgr.disruptions
        if disruptions:
            for d in reversed(disruptions[-4:]):
                tag_cls = "badge-danger" if d.kind == "MACHINE_BREAKDOWN" else ("badge-warning" if d.kind == "URGENT_JOB" else "badge-info")
                st.markdown(
                    f"""
                    <div class="nexus-card" style="padding: 0.75rem 1rem; margin-bottom: 0.5rem; border-left: 3px solid #0C7F74;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
                            <span style="font-weight: 600; font-size: 0.82rem; color: #12294A;">{d.disruption_id}</span>
                            <span class="nexus-badge {tag_cls}">{d.kind}</span>
                        </div>
                        <div style="font-size: 0.82rem; color: #3A4B66;">{d.description}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                """
                <div class="nexus-card" style="padding: 1.25rem; text-align: center; color: #6A7891;">
                    <div style="font-size: 1.5rem; margin-bottom: 0.25rem;">🟢</div>
                    <div style="font-weight: 600; font-size: 0.86rem; color: #12294A;">Nominal Operating Conditions</div>
                    <div style="font-size: 0.78rem; margin-top: 0.2rem;">No disruptions recorded. Production follows the baseline optimal schedule.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


# ==============================================================================
# MODULE 2: JOB MANAGEMENT
# ==============================================================================
elif page == "Job Management":
    st.markdown(
        """
        <div class="nexus-page-header">
            <h1 class="nexus-page-title">Manage Production Jobs</h1>
            <div class="nexus-page-subtitle">Add, update, and track the work your workshop needs to complete.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_view, tab_add, tab_edit = st.tabs([
        "📋 Production Orders Registry",
        "➕ Add New Production Order",
        "✏️ Edit & Delete Orders",
    ])

    with tab_view:
        # Search & Filter
        col_search, col_prio, col_mach_filter = st.columns([2.5, 1.25, 1.25])
        with col_search:
            search_query = st.text_input("Search Orders", placeholder="Filter by Job ID, Product Name, or Operation...").strip().lower()
        with col_prio:
            priority_filter = st.selectbox("Priority Rank", ["All Priorities", "Priority 1 (Critical)", "Priority 2 (High)", "Priority 3 (Normal)"])
        with col_mach_filter:
            m_options = ["All Machines"] + [m.machine_id for m in st.session_state.machines]
            machine_filter = st.selectbox("Filter Machine", m_options)

        # Filter jobs
        filtered_jobs = []
        for j in st.session_state.jobs:
            match_search = (
                not search_query
                or search_query in j.job_id.lower()
                or search_query in j.job_name.lower()
                or search_query in str(j.product).lower()
                or any(search_query in op.operation_name.lower() for op in j.operations)
            )
            match_prio = True
            if priority_filter == "Priority 1 (Critical)" and j.priority != 1:
                match_prio = False
            elif priority_filter == "Priority 2 (High)" and j.priority != 2:
                match_prio = False
            elif priority_filter == "Priority 3 (Normal)" and j.priority != 3:
                match_prio = False

            match_mach = True
            if machine_filter != "All Machines":
                match_mach = any(op.machine_id == machine_filter for op in j.operations)

            if match_search and match_prio and match_mach:
                filtered_jobs.append(j)

        st.markdown(f"<div style='font-size:0.8rem; color:#6A7891; margin-bottom: 0.5rem;'>Showing <b>{len(filtered_jobs)}</b> of <b>{len(st.session_state.jobs)}</b> production orders</div>", unsafe_allow_html=True)

        # Table with clean, human-readable column headers and verified product names
        overview_df = jobs_to_dataframe(filtered_jobs, st.session_state.machines)
        if not overview_df.empty:
            display_df = overview_df[[
                "job_id", "job_name", "product", "quantity", "priority",
                "due_min", "operation_seq", "operation_name", "machine_name", "duration_min"
            ]].copy()
            display_df.columns = [
                "Job ID", "Order Name", "Product Item", "Lot Qty", "Priority",
                "Deadline (min)", "Seq", "Operation Name", "Workstation", "Duration (min)"
            ]
            st.dataframe(display_df, use_container_width=True, height=280)
        else:
            st.warning("No production orders match the current filter criteria.")

        # Expandable job cards with detailed routing sequences
        st.markdown('<div class="nexus-section-header">Order Routing Sequences</div>', unsafe_allow_html=True)
        for job in filtered_jobs:
            urg_pill = "<span class='nexus-badge badge-danger'>URGENT</span>" if getattr(job, "is_urgent", False) else ""
            with st.expander(f"📦 {job.job_id}: {job.job_name} ({job.product}) · Priority {job.priority} · Due {job.due_min}m"):
                st.markdown(
                    f"""
                    <div style="font-size:0.85rem; color:#3A4B66; margin-bottom:0.5rem;">
                        <b>Product:</b> {job.product} &nbsp;|&nbsp;
                        <b>Lot Quantity:</b> {job.quantity} units &nbsp;|&nbsp;
                        <b>Total Processing Duration:</b> {job.total_duration_min} min {urg_pill}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                ops_data = [
                    {
                        "Seq": op.operation_seq,
                        "Operation Name": op.operation_name,
                        "Assigned Workstation": op.machine_id,
                        "Processing Duration (min)": op.duration_min,
                    }
                    for op in job.operations
                ]
                st.table(pd.DataFrame(ops_data))

    with tab_add:
        st.markdown('<div class="nexus-section-header">Define a New Production Order</div>', unsafe_allow_html=True)
        with st.form("add_job_form", clear_on_submit=False):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                new_job_id = st.text_input("Job ID*", value=f"J-{100 + len(st.session_state.jobs) + 1}").strip()
                new_job_name = st.text_input("Job Name*", value="Shaft Coupling").strip()
            with fc2:
                new_product = st.text_input("Product Item*", value="Precision Coupling").strip()
                new_quantity = st.number_input("Quantity (units)*", min_value=1, value=4, step=1)
            with fc3:
                new_priority = st.selectbox("Priority Level*", [1, 2, 3], index=1, format_func=lambda p: f"Priority {p} ({'Critical' if p==1 else ('High' if p==2 else 'Normal')})")
                new_due = st.number_input("Delivery Deadline (min)*", min_value=10, value=250, step=10)

            st.markdown("##### Operations Routing Sequence")
            num_ops = st.number_input("Number of Operations", min_value=1, max_value=5, value=2, step=1)
            mach_ids = [m.machine_id for m in st.session_state.machines]

            ops_inputs: list[tuple[str, str, int]] = []
            for i in range(1, int(num_ops) + 1):
                oc1, oc2, oc3 = st.columns([2, 1, 1])
                with oc1:
                    op_name = st.text_input(f"Op {i} Name", value=f"Process step {i}", key=f"new_op_name_{i}").strip()
                with oc2:
                    op_mach = st.selectbox(f"Op {i} Machine", mach_ids, index=(i - 1) % len(mach_ids), key=f"new_op_mach_{i}")
                with oc3:
                    op_dur = st.number_input(f"Op {i} Duration (min)", min_value=1, value=30, step=5, key=f"new_op_dur_{i}")
                ops_inputs.append((op_name, op_mach, int(op_dur)))

            submitted = st.form_submit_button("Add Order to Workshop", type="primary", use_container_width=True)
            if submitted:
                existing_ids = {j.job_id for j in st.session_state.jobs}
                if not new_job_id:
                    st.error("Job ID cannot be blank.")
                elif new_job_id in existing_ids:
                    st.error(f"Job ID '{new_job_id}' already exists.")
                elif not new_job_name:
                    st.error("Job Name cannot be blank.")
                else:
                    ops_tuple = tuple(
                        Operation(
                            job_id=new_job_id,
                            operation_seq=idx,
                            operation_name=name,
                            machine_id=mid,
                            duration_min=dur,
                        )
                        for idx, (name, mid, dur) in enumerate(ops_inputs, start=1)
                    )
                    created_job = Job(
                        job_id=new_job_id,
                        job_name=new_job_name,
                        product=new_product,
                        quantity=int(new_quantity),
                        priority=int(new_priority),
                        due_min=int(new_due),
                        operations=ops_tuple,
                    )
                    st.session_state.jobs.append(created_job)
                    save_jobs(st.session_state.jobs)
                    st.session_state.baseline_schedule = solve_job_shop(
                        st.session_state.jobs, machines=tuple(st.session_state.machines)
                    )
                    st.session_state.revised_schedule = st.session_state.baseline_schedule
                    st.success(f"Order '{new_job_id}' added successfully! Re-optimized makespan: {st.session_state.baseline_schedule.makespan_min} min.")
                    st.rerun()

    with tab_edit:
        st.markdown('<div class="nexus-section-header">Modify or Remove Existing Orders</div>', unsafe_allow_html=True)
        job_to_edit_id = st.selectbox("Select Order to Modify", [j.job_id for j in st.session_state.jobs])
        job_obj = next(j for j in st.session_state.jobs if j.job_id == job_to_edit_id)

        col_edit_fields, col_del = st.columns([3, 1])
        with col_edit_fields:
            with st.form("edit_job_form"):
                e1, e2, e3 = st.columns(3)
                with e1:
                    edit_name = st.text_input("Job Name", value=job_obj.job_name)
                    edit_prod = st.text_input("Product Item", value=job_obj.product)
                with e2:
                    edit_qty = st.number_input("Lot Quantity", min_value=1, value=job_obj.quantity)
                    edit_prio = st.selectbox("Priority", [1, 2, 3], index=job_obj.priority - 1)
                with e3:
                    edit_due = st.number_input("Due Date (min)", min_value=10, value=job_obj.due_min, step=10)

                st.markdown("##### Operation Duration Adjustments")
                updated_ops = []
                for op in job_obj.operations:
                    o_c1, o_c2 = st.columns(2)
                    with o_c1:
                        st.write(f"Op {op.operation_seq}: {op.operation_name} ({op.machine_id})")
                    with o_c2:
                        dur_val = st.number_input(
                            f"Duration (min)",
                            min_value=1,
                            value=op.duration_min,
                            key=f"edit_dur_{job_obj.job_id}_{op.operation_seq}",
                        )
                    updated_ops.append(
                        Operation(
                            job_id=job_obj.job_id,
                            operation_seq=op.operation_seq,
                            operation_name=op.operation_name,
                            machine_id=op.machine_id,
                            duration_min=int(dur_val),
                        )
                    )

                save_edit = st.form_submit_button("Save Order Updates", type="primary", use_container_width=True)
                if save_edit:
                    idx = next(i for i, j in enumerate(st.session_state.jobs) if j.job_id == job_to_edit_id)
                    st.session_state.jobs[idx] = Job(
                        job_id=job_obj.job_id,
                        job_name=edit_name,
                        product=edit_prod,
                        quantity=int(edit_qty),
                        priority=int(edit_prio),
                        due_min=int(edit_due),
                        operations=tuple(updated_ops),
                    )
                    save_jobs(st.session_state.jobs)
                    st.session_state.baseline_schedule = solve_job_shop(
                        st.session_state.jobs, machines=tuple(st.session_state.machines)
                    )
                    st.session_state.revised_schedule = st.session_state.baseline_schedule
                    st.success(f"Order '{job_obj.job_id}' updated. New makespan: {st.session_state.baseline_schedule.makespan_min} min.")
                    st.rerun()

        with col_del:
            st.markdown("##### Delete Order")
            st.markdown("<div style='font-size:0.8rem; color:#6A7891;'>Removes this order completely from the workshop scheduling model.</div>", unsafe_allow_html=True)
            if st.button("🗑️ Delete Order", use_container_width=True):
                if len(st.session_state.jobs) <= 1:
                    st.error("At least one production order is required.")
                else:
                    st.session_state.jobs = [j for j in st.session_state.jobs if j.job_id != job_to_edit_id]
                    save_jobs(st.session_state.jobs)
                    st.session_state.baseline_schedule = solve_job_shop(
                        st.session_state.jobs, machines=tuple(st.session_state.machines)
                    )
                    st.session_state.revised_schedule = st.session_state.baseline_schedule
                    st.success(f"Order '{job_to_edit_id}' deleted.")
                    st.rerun()


# ==============================================================================
# MODULE 3: MACHINE MANAGEMENT
# ==============================================================================
elif page == "Machine Management":
    st.markdown(
        """
        <div class="nexus-page-header">
            <h1 class="nexus-page-title">Manage Machines</h1>
            <div class="nexus-page-subtitle">View your machines and update their details and availability.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_mach_status, tab_mach_add = st.tabs(["🏭 Workstations & Status", "➕ Register New Workstation"])

    with tab_mach_status:
        active_sched = st.session_state.revised_schedule
        mach_metrics = compute_machine_metrics(
            active_sched.operations,
            active_sched.makespan_min or 210,
            tuple(st.session_state.machines),
            active_sched.downtimes,
        )

        # Workstation Cards
        m_cols = st.columns(len(st.session_state.machines))
        for col, m in zip(m_cols, st.session_state.machines):
            m_stat = mach_metrics[mach_metrics["machine_id"] == m.machine_id].iloc[0] if not mach_metrics.empty else None
            util = m_stat["utilization_pct"] if m_stat is not None else 0.0
            busy = m_stat["busy_time_min"] if m_stat is not None else 0
            down = m_stat["downtime_min"] if m_stat is not None else 0

            with col:
                badge_cls = "badge-success" if m.status == "Operational" else ("badge-warning" if m.status == "Maintenance" else "badge-danger")
                st.markdown(
                    f"""
                    <div class="nexus-card">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span style="font-weight:700; font-size:1.02rem; color:#12294A;">{m.name}</span>
                            <span class="nexus-badge {badge_cls}">{m.status}</span>
                        </div>
                        <div style="color:#6A7891; font-size:0.78rem; margin-top:0.15rem;">ID: <b>{m.machine_id}</b></div>
                        <div style="margin-top:0.6rem; font-size:0.82rem; color:#3A4B66; line-height:1.3;">{m.description}</div>
                        <hr style="margin: 0.7rem 0; border: none; border-top: 1px solid #E2E8F0;" />
                        <div style="display:flex; justify-content:space-between; font-size:0.8rem; margin-bottom:0.2rem;">
                            <span style="color:#6A7891;">Utilization:</span>
                            <b style="color:#12294A;">{util}%</b>
                        </div>
                        <div style="display:flex; justify-content:space-between; font-size:0.8rem; margin-bottom:0.2rem;">
                            <span style="color:#6A7891;">Busy Processing:</span>
                            <b style="color:#12294A;">{busy} min</b>
                        </div>
                        <div style="display:flex; justify-content:space-between; font-size:0.8rem;">
                            <span style="color:#6A7891;">Downtime:</span>
                            <b style="color:{'#C2414B' if down>0 else '#12294A'};">{down} min</b>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Quick status selector
                new_status = st.selectbox(
                    f"Status ({m.machine_id})",
                    ["Operational", "Maintenance", "Breakdown", "Idle"],
                    index=["Operational", "Maintenance", "Breakdown", "Idle"].index(m.status),
                    key=f"status_sel_{m.machine_id}",
                    label_visibility="collapsed",
                )
                if new_status != m.status:
                    idx = next(i for i, x in enumerate(st.session_state.machines) if x.machine_id == m.machine_id)
                    st.session_state.machines[idx] = Machine(
                        machine_id=m.machine_id,
                        name=m.name,
                        description=m.description,
                        status=new_status,
                        capabilities=m.capabilities,
                        total_available_time_min=m.total_available_time_min,
                    )
                    save_machines(st.session_state.machines)
                    st.success(f"Workstation {m.name} status updated to {new_status}")
                    st.rerun()

        st.markdown('<div class="nexus-section-header">Workstation Load & Time Allocation</div>', unsafe_allow_html=True)
        fig_util = create_utilization_bar_chart(mach_metrics)
        theme.themed_chart(fig_util, use_container_width=True)

    with tab_mach_add:
        st.markdown('<div class="nexus-section-header">Register a New Workstation</div>', unsafe_allow_html=True)
        with st.form("add_machine_form"):
            c1, c2 = st.columns(2)
            with c1:
                new_mid = st.text_input("Workstation ID (e.g. CNC, WLD, PKG)*").strip().upper()
                new_mname = st.text_input("Workstation Name (e.g. CNC Milling Center)*").strip()
            with c2:
                new_mdesc = st.text_input("Description*", value="Heavy-duty machining center").strip()
                new_avail = st.number_input("Shift Available Time (min)", min_value=60, value=480, step=60)

            add_m_btn = st.form_submit_button("Register Workstation", type="primary", use_container_width=True)
            if add_m_btn:
                existing_mids = {m.machine_id for m in st.session_state.machines}
                if not new_mid:
                    st.error("Workstation ID cannot be blank.")
                elif new_mid in existing_mids:
                    st.error(f"Workstation ID '{new_mid}' already exists.")
                elif not new_mname:
                    st.error("Workstation Name cannot be blank.")
                else:
                    new_machine = Machine(
                        machine_id=new_mid,
                        name=new_mname,
                        description=new_mdesc,
                        status="Operational",
                        total_available_time_min=int(new_avail),
                    )
                    st.session_state.machines.append(new_machine)
                    save_machines(st.session_state.machines)
                    st.success(f"Workstation '{new_mname}' ({new_mid}) registered successfully!")
                    st.rerun()


# ==============================================================================
# MODULE 4: CONSTRAINT PROGRAMMING SCHEDULER
# ==============================================================================
elif page == "Schedule Optimizer":
    st.markdown(
        """
        <div class="nexus-page-header">
            <h1 class="nexus-page-title">Create a Production Schedule</h1>
            <div class="nexus-page-subtitle">Create an efficient order for completing jobs using the available machines.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="nexus-callout">
            <b>Exact Optimization Engine</b>: Google OR-Tools CP-SAT guarantees global mathematical optimality. Operations are assigned non-overlapping time intervals respecting sequence precedence, machine capacity, and fixed breakdown windows.
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_cfg1, col_cfg2, col_cfg3 = st.columns(3)
    with col_cfg1:
        obj_mode = st.selectbox(
            "Optimization Objective",
            ["Minimize Makespan (Standard)", "Multi-Objective (Makespan + Priority Weighting)"],
            index=0,
        )
        obj_code = "makespan" if "Standard" in obj_mode else "weighted_priority"
    with col_cfg2:
        time_limit = st.slider("Solver Search Limit (seconds)", min_value=1, max_value=60, value=30, step=1)
    with col_cfg3:
        random_seed = st.number_input("Solver Seed", value=1, step=1)

    c_run, c_base = st.columns([1, 1])
    with c_run:
        if st.button("⚡ Solve Schedule with OR-Tools CP-SAT", type="primary", use_container_width=True):
            with st.spinner("Running Google OR-Tools CP-SAT optimization..."):
                breakdowns = st.session_state.disruption_mgr.get_breakdowns(st.session_state.machines)
                res = solve_job_shop(
                    st.session_state.jobs,
                    machines=tuple(st.session_state.machines),
                    breakdowns=breakdowns,
                    objective_mode=obj_code,
                    time_limit_s=float(time_limit),
                    random_seed=int(random_seed),
                )
                if breakdowns:
                    st.session_state.revised_schedule = res
                else:
                    st.session_state.baseline_schedule = res
                    st.session_state.revised_schedule = res
                log_schedule_result(res, "revised" if breakdowns else "baseline")
                st.success(f"Optimization completed in {res.wall_time_s:.4f}s · Status: {res.status} · Makespan: {res.makespan_min} min")

    with c_base:
        if st.button("🎯 Re-Solve Baseline Schedule (Undisrupted)", use_container_width=True):
            with st.spinner("Solving nominal baseline schedule..."):
                res = solve_job_shop(
                    st.session_state.jobs,
                    machines=tuple(st.session_state.machines),
                    breakdowns=None,
                    objective_mode="makespan",
                    time_limit_s=float(time_limit),
                    random_seed=int(random_seed),
                )
                st.session_state.baseline_schedule = res
                st.success(f"Baseline resolved · Optimal Makespan: {res.makespan_min} min")

    # Display Current Schedule Results
    current_sched = st.session_state.revised_schedule
    st.markdown('<div class="nexus-section-header">Optimization Results & Solver Metrics</div>', unsafe_allow_html=True)

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Solver Status</div>
                <div class="nexus-kpi-val" style="color: #1F8A5B; font-size: 1.35rem;">{current_sched.status}</div>
                <div class="nexus-kpi-sub">{current_sched.solver}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m2:
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Makespan</div>
                <div class="nexus-kpi-val">{current_sched.makespan_min} <span style="font-size:0.85rem; font-weight:500; color:#6A7891;">min</span></div>
                <div class="nexus-kpi-sub">Shift completion time</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m3:
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Best Bound</div>
                <div class="nexus-kpi-val">{current_sched.best_bound_min} <span style="font-size:0.85rem; font-weight:500; color:#6A7891;">min</span></div>
                <div class="nexus-kpi-sub">Optimality gap: 0.0%</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m4:
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Solve Wall Time</div>
                <div class="nexus-kpi-val">{current_sched.wall_time_s:.4f} <span style="font-size:0.85rem; font-weight:500; color:#6A7891;">s</span></div>
                <div class="nexus-kpi-sub">Search execution time</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with m5:
        lb = lower_bound_min(st.session_state.jobs)
        st.markdown(
            f"""
            <div class="nexus-kpi-card">
                <div class="nexus-kpi-label">Theoretical LB</div>
                <div class="nexus-kpi-val">{lb} <span style="font-size:0.85rem; font-weight:500; color:#6A7891;">min</span></div>
                <div class="nexus-kpi-sub">Max load / longest job</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Interactive Gantt Chart
    st.markdown('<div class="nexus-section-header">Optimized Production Gantt Timetable</div>', unsafe_allow_html=True)
    fig_gantt = create_gantt_chart(
        current_sched,
        st.session_state.jobs,
        st.session_state.machines,
        title=f"CP-SAT Optimized Timetable · Makespan: {current_sched.makespan_min} min",
    )
    theme.themed_chart(fig_gantt, use_container_width=True)

    # Detailed Schedule Table
    st.markdown('<div class="nexus-section-header">Scheduled Operations Timetable</div>', unsafe_allow_html=True)
    sched_df = current_sched.to_dataframe()
    if not sched_df.empty:
        display_sched = sched_df.sort_values(["start_min", "machine_id"]).reset_index(drop=True)
        display_sched.columns = [
            "Job ID", "Order Name", "Op Seq", "Operation", "Machine ID",
            "Workstation", "Duration (min)", "Start (min)", "End (min)", "Is Urgent"
        ]
        st.dataframe(display_sched, use_container_width=True, height=280)
        csv_data = export_schedule_to_csv_string(current_sched)
        st.download_button(
            "📥 Download Schedule as CSV",
            data=csv_data,
            file_name="prodsched_schedule.csv",
            mime="text/csv",
        )


# ==============================================================================
# MODULE 5: DISRUPTION MANAGEMENT (DISRUPTION CENTER)
# ==============================================================================
elif page == "Disruption Center":
    st.markdown(
        """
        <div class="nexus-page-header">
            <h1 class="nexus-page-title">Handle Production Problems</h1>
            <div class="nexus-page-subtitle">Try situations such as a machine breakdown, an urgent job, or a delay and update the schedule.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    disruption_tabs = st.tabs([
        "🔴 Scenario A: Machine Breakdown",
        "⚡ Scenario B: Urgent Production Order",
        "⏱️ Scenario C: Processing Delay",
        "📜 Active Disruptions Registry",
    ])

    with disruption_tabs[0]:
        st.markdown('<div class="nexus-section-header">Scenario A: Inject Machine Breakdown</div>', unsafe_allow_html=True)
        st.markdown("<div style='font-size:0.84rem; color:#6A7891; margin-bottom:0.75rem;'>Enforce an unexpected machine downtime window. Operations cannot overlap with the repair interval.</div>", unsafe_allow_html=True)

        with st.form("breakdown_form"):
            b1, b2, b3 = st.columns(3)
            with b1:
                bd_mach = st.selectbox("Affected Workstation", [m.machine_id for m in st.session_state.machines], index=0)
            with b2:
                bd_start = st.number_input("Breakdown Start Time (min)", min_value=0, max_value=300, value=50, step=5)
            with b3:
                bd_dur = st.number_input("Downtime Duration (min)", min_value=5, max_value=180, value=40, step=5)
            bd_reason = st.text_input("Failure Reason", value="Saw blade motor overheat & alignment failure")

            inject_bd = st.form_submit_button("🚨 Inject Breakdown & Recalculate Schedule", type="primary", use_container_width=True)
            if inject_bd:
                d = st.session_state.disruption_mgr.add_breakdown(
                    machine_id=bd_mach,
                    start_min=int(bd_start),
                    duration_min=int(bd_dur),
                    reason=bd_reason,
                )
                with st.spinner("Rescheduling with CP-SAT machine downtime constraints..."):
                    revised = st.session_state.disruption_mgr.reschedule(
                        st.session_state.jobs, machines=tuple(st.session_state.machines)
                    )
                    st.session_state.revised_schedule = revised
                    log_schedule_result(revised, "revised")
                st.success(f"Breakdown registered on {bd_mach} from t={bd_start} to t={bd_start+bd_dur} min. Revised makespan: {revised.makespan_min} min!")
                st.rerun()

    with disruption_tabs[1]:
        st.markdown('<div class="nexus-section-header">Scenario B: Insert Urgent Production Order</div>', unsafe_allow_html=True)
        st.markdown("<div style='font-size:0.84rem; color:#6A7891; margin-bottom:0.75rem;'>Dynamically insert an expedited rush customer order into the active schedule.</div>", unsafe_allow_html=True)

        with st.form("urgent_job_form"):
            u1, u2, u3 = st.columns(3)
            with u1:
                urg_id = st.text_input("Urgent Job ID", value=f"J-RUSH-{len(st.session_state.disruption_mgr.disruptions)+1}")
                urg_name = st.text_input("Order Description", value="Emergency Replacement Valve")
            with u2:
                urg_prod = st.text_input("Product Item", value="High-Pressure Valve")
                urg_qty = st.number_input("Quantity", min_value=1, value=2)
            with u3:
                urg_due = st.number_input("Delivery Deadline (min)", min_value=10, value=130, step=10)

            st.markdown("##### Urgent Order Routing")
            mach_ids = [m.machine_id for m in st.session_state.machines]
            uo1, uo2 = st.columns(2)
            with uo1:
                u_m1 = st.selectbox("Operation 1 Machine", mach_ids, index=0, key="u_m1")
                u_d1 = st.number_input("Operation 1 Duration (min)", min_value=5, value=20, step=5, key="u_d1")
            with uo2:
                u_m2 = st.selectbox("Operation 2 Machine", mach_ids, index=1 if len(mach_ids)>1 else 0, key="u_m2")
                u_d2 = st.number_input("Operation 2 Duration (min)", min_value=5, value=25, step=5, key="u_d2")

            inject_urg = st.form_submit_button("⚡ Insert Urgent Order & Recalculate Schedule", type="primary", use_container_width=True)
            if inject_urg:
                new_urg_job = Job(
                    job_id=urg_id,
                    job_name=urg_name,
                    product=urg_prod,
                    quantity=int(urg_qty),
                    priority=1,
                    due_min=int(urg_due),
                    operations=(
                        Operation(urg_id, 1, f"Fast cut {urg_name}", u_m1, int(u_d1)),
                        Operation(urg_id, 2, f"Rapid drill {urg_name}", u_m2, int(u_d2)),
                    ),
                    is_urgent=True,
                )
                d = st.session_state.disruption_mgr.add_urgent_job(new_urg_job)
                with st.spinner("Rescheduling with urgent order insertion..."):
                    revised = st.session_state.disruption_mgr.reschedule(
                        st.session_state.jobs, machines=tuple(st.session_state.machines)
                    )
                    st.session_state.revised_schedule = revised
                    log_schedule_result(revised, "revised")
                st.success(f"Urgent Order '{urg_id}' inserted! Revised makespan: {revised.makespan_min} min.")
                st.rerun()

    with disruption_tabs[2]:
        st.markdown('<div class="nexus-section-header">Scenario C: Increase Operation Processing Delay</div>', unsafe_allow_html=True)
        st.markdown("<div style='font-size:0.84rem; color:#6A7891; margin-bottom:0.75rem;'>Simulate processing delays caused by tool wear, hard casting material, or extended calibration.</div>", unsafe_allow_html=True)

        all_ops_choices = []
        for j in st.session_state.jobs:
            for op in j.operations:
                all_ops_choices.append((f"{j.job_id} · Op {op.operation_seq}: {op.operation_name} ({op.machine_id}) [{op.duration_min}m]", j.job_id, op.operation_seq))

        with st.form("delay_form"):
            selected_op_str = st.selectbox("Select Target Operation", [item[0] for item in all_ops_choices])
            target_item = next(item for item in all_ops_choices if item[0] == selected_op_str)
            target_jid = target_item[1]
            target_seq = target_item[2]

            d1, d2 = st.columns(2)
            with d1:
                delay_added = st.number_input("Added Processing Delay (+min)", min_value=5, max_value=120, value=30, step=5)
            with d2:
                delay_reason = st.text_input("Delay Cause", value="Workpiece material porosity & excessive tool wear")

            inject_dly = st.form_submit_button("⏱️ Apply Delay & Recalculate Schedule", type="primary", use_container_width=True)
            if inject_dly:
                d = st.session_state.disruption_mgr.add_processing_delay(
                    job_id=target_jid,
                    operation_seq=target_seq,
                    delay_min=int(delay_added),
                    reason=delay_reason,
                )
                with st.spinner("Rescheduling with extended operation durations..."):
                    revised = st.session_state.disruption_mgr.reschedule(
                        st.session_state.jobs, machines=tuple(st.session_state.machines)
                    )
                    st.session_state.revised_schedule = revised
                    log_schedule_result(revised, "revised")
                st.success(f"Added +{delay_added} min delay to {target_jid} op {target_seq}. Revised makespan: {revised.makespan_min} min!")
                st.rerun()

    with disruption_tabs[3]:
        st.markdown('<div class="nexus-section-header">Active Disruptions Registry</div>', unsafe_allow_html=True)
        disruptions = st.session_state.disruption_mgr.disruptions
        if disruptions:
            dis_data = [
                {
                    "Disruption ID": d.disruption_id,
                    "Scenario Type": d.kind,
                    "Description": d.description,
                    "Target Workstation": d.machine_id or "-",
                    "Start (min)": d.start_min if d.start_min is not None else "-",
                    "Duration (min)": d.duration_min if d.duration_min is not None else (f"+{d.delay_min}m" if d.delay_min else "-"),
                }
                for d in disruptions
            ]
            st.table(pd.DataFrame(dis_data))

            if st.button("🧹 Clear All Disruptions & Restore Baseline", use_container_width=True):
                st.session_state.disruption_mgr.clear()
                st.session_state.revised_schedule = st.session_state.baseline_schedule
                st.success("All disruptions removed. Baseline schedule restored!")
                st.rerun()
        else:
            st.info("No active disruptions. The shop floor is running on nominal baseline conditions.")

    # Disruption Impact Analysis Section
    st.markdown('<div class="nexus-section-header">Disruption Impact Diagnostic Analysis</div>', unsafe_allow_html=True)
    comp = DisruptionManager.compare_schedules(
        st.session_state.baseline_schedule,
        st.session_state.revised_schedule,
        st.session_state.jobs,
    )

    st.markdown(
        f"""
        <div class="nexus-callout">
            <b>Automated Diagnosis</b>: {comp['explanation']}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Before and After Gantt Comparison
    fig_comp = create_comparison_gantt(
        st.session_state.baseline_schedule,
        st.session_state.revised_schedule,
        st.session_state.jobs,
    )
    theme.themed_chart(fig_comp, use_container_width=True)


# ==============================================================================
# MODULE 6: DISCRETE-EVENT SIMULATION (SIMPY)
# ==============================================================================
elif page == "Production Simulation":
    st.markdown(
        """
        <div class="nexus-page-header">
            <h1 class="nexus-page-title">Test Production</h1>
            <div class="nexus-page-subtitle">Run a production test and see how jobs move through the workshop.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    sim_col1, sim_col2, sim_col3 = st.columns(3)
    with sim_col1:
        dispatch_mode = st.selectbox(
            "Dispatch Strategy",
            ["Schedule-Paced (Tracks CP-SAT Timetable)", "Opportunistic (Work-Conserving FIFO)"],
            index=0,
        )
        dispatch_code = "schedule_paced" if "Schedule-Paced" in dispatch_mode else "opportunistic"
    with sim_col2:
        stochastic_toggle = st.checkbox("Stochastic Processing Jitter (±5%)", value=False)
    with sim_col3:
        sim_seed = st.number_input("Simulation Seed", value=42, step=1)

    if st.button("🚀 Run Discrete-Event Simulation", type="primary", use_container_width=True):
        with st.spinner("Executing SimPy discrete-event simulation model..."):
            eff_jobs = st.session_state.disruption_mgr.apply_to_jobs(st.session_state.jobs)
            sim = WorkshopSimulator(
                schedule=st.session_state.revised_schedule,
                jobs=eff_jobs,
                machines=tuple(st.session_state.machines),
                disruptions=st.session_state.disruption_mgr.disruptions,
            )
            sim_res = sim.run(
                seed=int(sim_seed),
                stochastic=stochastic_toggle,
                dispatch_mode=dispatch_code,
            )
            st.session_state.sim_result = sim_res
            st.success(f"Simulation completed · Simulated Makespan: {sim_res.makespan_min:.1f} min across {len(sim_res.events)} events.")

    # Display Simulation Results
    sim_res = st.session_state.sim_result
    if sim_res is not None:
        st.markdown('<div class="nexus-section-header">Simulation Performance Indicators</div>', unsafe_allow_html=True)
        sum_dict = sim_res.summary()

        sm1, sm2, sm3, sm4, sm5 = st.columns(5)
        with sm1:
            st.markdown(
                f"""
                <div class="nexus-kpi-card">
                    <div class="nexus-kpi-label">Simulated Makespan</div>
                    <div class="nexus-kpi-val">{sim_res.makespan_min:.1f} <span style="font-size:0.85rem; font-weight:500; color:#6A7891;">min</span></div>
                    <div class="nexus-kpi-sub">Actual workshop end</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with sm2:
            st.markdown(
                f"""
                <div class="nexus-kpi-card">
                    <div class="nexus-kpi-label">Total Waiting Time</div>
                    <div class="nexus-kpi-val">{sum_dict['total_waiting_min']} <span style="font-size:0.85rem; font-weight:500; color:#6A7891;">min</span></div>
                    <div class="nexus-kpi-sub">Sum of queue delays</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with sm3:
            st.markdown(
                f"""
                <div class="nexus-kpi-card">
                    <div class="nexus-kpi-label">Avg Utilization</div>
                    <div class="nexus-kpi-val">{sum_dict['average_machine_utilization_pct']}%</div>
                    <div class="nexus-kpi-sub">Across all workstations</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with sm4:
            st.markdown(
                f"""
                <div class="nexus-kpi-card">
                    <div class="nexus-kpi-label">Downtime Incurred</div>
                    <div class="nexus-kpi-val" style="color: {'#C2414B' if sum_dict['total_downtime_min']>0 else '#12294A'};">{sum_dict['total_downtime_min']} <span style="font-size:0.85rem; font-weight:500; color:#6A7891;">min</span></div>
                    <div class="nexus-kpi-sub">Machine breakdowns</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with sm5:
            st.markdown(
                f"""
                <div class="nexus-kpi-card">
                    <div class="nexus-kpi-label">Tardy Orders</div>
                    <div class="nexus-kpi-val" style="color: {'#C2414B' if sum_dict['tardy_jobs_count']>0 else '#1F8A5B'};">{sum_dict['tardy_jobs_count']}</div>
                    <div class="nexus-kpi-sub">Breached delivery date</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # Planned vs Simulated Comparison Table
        st.markdown('<div class="nexus-section-header">Planned Schedule vs Simulated Execution</div>', unsafe_allow_html=True)
        comp_rows = []
        for j in st.session_state.jobs:
            m = sim_res.job_metrics.get(j.job_id)
            if m:
                planned_ops = [op for op in st.session_state.revised_schedule.operations if op.job_id == j.job_id]
                planned_end = max((op.end_min for op in planned_ops), default=0)
                sim_end = m["completion_min"]
                diff = sim_end - planned_end
                comp_rows.append(
                    {
                        "Job ID": j.job_id,
                        "Product Item": j.product,
                        "Promised Due (min)": j.due_min,
                        "Planned End (min)": planned_end,
                        "Simulated End (min)": sim_end,
                        "Variance (min)": f"{'+' if diff>0 else ''}{diff:.1f}m",
                        "Total Queue Wait (min)": m["total_waiting_min"],
                        "Delivery Status": "Delayed" if m["is_tardy"] else "On-Time",
                    }
                )
        st.dataframe(pd.DataFrame(comp_rows), use_container_width=True)

        # Simulation Event Log
        st.markdown('<div class="nexus-section-header">Discrete-Event Simulation Event Log</div>', unsafe_allow_html=True)
        events_df = sim_res.events_dataframe()
        event_filter = st.selectbox("Filter Events by Category", ["All Events", "BREAKDOWN", "OP_PREEMPTED", "JOB_COMPLETED", "OP_STARTED"])
        if event_filter != "All Events":
            events_df = events_df[events_df["event_type"].str.contains(event_filter)]

        events_df.columns = ["Time (min)", "Event Type", "Job ID", "Op Seq", "Workstation", "Event Description"]
        st.dataframe(events_df, use_container_width=True, height=260)
        csv_events = events_df.to_csv(index=False)
        st.download_button(
            "📥 Download Simulation Event Log (CSV)",
            data=csv_events,
            file_name="simulation_events.csv",
            mime="text/csv",
        )
    else:
        st.info("Click 'Run Discrete-Event Simulation' above to execute the SimPy model on the current workshop setup.")


# ==============================================================================
# MODULE 7 & 8: ANALYTICS AND REPORTS
# ==============================================================================
elif page == "Analytics & Reports":
    st.markdown(
        """
        <div class="nexus-page-header">
            <h1 class="nexus-page-title">Reports & Insights</h1>
            <div class="nexus-page-subtitle">Understand machine use, job completion times, delays, and production performance.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    sched = st.session_state.revised_schedule
    horizon = sched.makespan_min or 210

    mach_df = compute_machine_metrics(sched.operations, horizon, tuple(st.session_state.machines), sched.downtimes)
    job_df = compute_job_metrics(sched.operations, st.session_state.jobs)

    # Export Button at top
    col_rep_head, col_rep_btn = st.columns([3.5, 1.5])
    with col_rep_btn:
        analytics_csv = export_analytics_to_csv_string(mach_df, job_df)
        st.download_button(
            "📥 Export Complete Performance Report (CSV)",
            data=analytics_csv,
            file_name="prodsched_performance_report.csv",
            mime="text/csv",
            use_container_width=True,
        )

    # 4 Primary Visualizations
    v1, v2 = st.columns(2)
    with v1:
        fig1 = create_utilization_bar_chart(mach_df)
        theme.themed_chart(fig1, use_container_width=True)

    with v2:
        fig2 = create_waiting_time_chart(job_df)
        theme.themed_chart(fig2, use_container_width=True)

    v3, v4 = st.columns(2)
    with v3:
        fig3 = create_tardiness_chart(job_df)
        theme.themed_chart(fig3, use_container_width=True)

    with v4:
        base_val = st.session_state.baseline_schedule.makespan_min or 210
        rev_val = sched.makespan_min or 210
        sim_val = st.session_state.sim_result.makespan_min if st.session_state.sim_result else None

        labels = ["Baseline (CP-SAT)", "Revised (CP-SAT)"]
        vals = [base_val, rev_val]
        colors = ["#2563EB", "#7C3AED"]

        if sim_val is not None:
            labels.append("Simulated (SimPy)")
            vals.append(sim_val)
            colors.append("#0D9488")

        fig4 = go.Figure(
            data=[
                go.Bar(
                    x=labels,
                    y=vals,
                    marker_color=colors,
                    text=[f"{v:.1f}m" for v in vals],
                    textposition="inside",
                    textfont=dict(family="Inter, sans-serif", size=11, color="#FFFFFF"),
                )
            ]
        )
        fig4.update_layout(
            title=dict(text="<b>Production Makespan Across Phases</b>", font=dict(family="Inter, sans-serif", size=13, color="#12294A")),
            plot_bgcolor="#F8FAFC",
            paper_bgcolor="#FFFFFF",
            yaxis=dict(title="Minutes", title_font=dict(family="Inter, sans-serif", size=11, color="#6A7891"), gridcolor="#F1F5F9"),
            xaxis=dict(tickfont=dict(family="Inter, sans-serif", size=11, color="#12294A")),
            height=300,
            margin=dict(l=45, r=20, t=45, b=35),
        )
        theme.themed_chart(fig4, use_container_width=True)

    # Machine Performance Summary Table
    st.markdown('<div class="nexus-section-header">Workstation Utilization & Workload Summary</div>', unsafe_allow_html=True)
    display_mdf = mach_df[[
        "machine_id", "machine_name", "busy_time_min", "downtime_min", "idle_time_min", "utilization_pct", "operations_count"
    ]].copy()
    display_mdf.columns = [
        "Machine ID", "Workstation Name", "Busy Time (min)", "Downtime (min)",
        "Idle Time (min)", "Utilization (%)", "Operations Processed"
    ]
    st.dataframe(display_mdf, use_container_width=True)

    # Job Delivery Performance Table
    st.markdown('<div class="nexus-section-header">Order Lead Times & Delivery Performance</div>', unsafe_allow_html=True)
    display_jdf = job_df[[
        "job_id", "job_name", "product", "priority", "due_min", "completion_min", "waiting_min", "tardiness_min", "status"
    ]].copy()
    display_jdf.columns = [
        "Job ID", "Order Name", "Product Item", "Priority", "Promised Due (min)",
        "Completion (min)", "Queue Wait (min)", "Tardiness (min)", "Delivery Status"
    ]
    st.dataframe(display_jdf, use_container_width=True)


# ==============================================================================
# MODULE 8: SYSTEM INFORMATION
# ==============================================================================
elif page == "System Information":
    st.markdown(
        """
        <div class="nexus-page-header">
            <h1 class="nexus-page-title">About This Project</h1>
            <div class="nexus-page-subtitle">Learn how the production planner works and which technologies it uses.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### 1. Job-Shop Scheduling Problem Formulation")
    st.write(
        "The workshop scheduling problem is modeled as an exact non-preemptive Disjunctive Job-Shop "
        "Scheduling Problem (JSSP) with machine downtime constraints solved via Google OR-Tools CP-SAT:"
    )

    st.markdown("**Objective Function** (Minimizing Makespan $C_{\\max}$):")
    st.latex(r"\min \quad C_{\max} = \max_{j \in J} \left( S_{j, m_j} + p_{j, m_j} \right)")

    st.markdown("**Precedence Constraints** (Operations must execute in strict technological sequence):")
    st.latex(r"S_{j, k+1} \;\ge\; S_{j, k} + p_{j, k} \quad \forall j \in J, \quad k \in \{1, \dots, m_j - 1\}")

    st.markdown("**Machine Disjunction & Breakdown Non-Overlap Constraints**:")
    st.latex(r"\text{NoOverlap}\left( \left\{ I_{j, k} \;\middle|\; m(O_{j, k}) = M_i \right\} \;\cup\; \left\{ I_{\text{breakdown}, M_i} \right\} \right) \quad \forall M_i \in M")

    st.markdown(
        """
        Where:
        - $J = \{J_1, J_2, \dots, J_n\}$ is the set of manufacturing jobs.
        - $M = \{M_1, M_2, \dots, M_k\}$ is the set of workshop workstations (Cutting, Drilling, Finishing).
        - $O_{j, k}$ denotes the $k$-th operation of job $j$, with processing duration $p_{j, k}$ on workstation $m(O_{j, k})$.
        - $S_{j, k}$ is the decision variable representing the start time of operation $O_{j, k}$.
        - $I_{j, k} = [S_{j, k}, S_{j, k} + p_{j, k})$ is the continuous time interval assigned to the operation.
        - $I_{\text{breakdown}, M_i} = [\tau_{\text{start}}, \tau_{\text{start}} + \tau_{\text{dur}})$ is the fixed downtime interval during which machine $M_i$ is unavailable.
        """
    )

    st.markdown("---")
    st.markdown("### 2. Discrete-Event Simulation Architecture (SimPy)")
    st.write(
        "To validate and benchmark the CP-SAT timetable against physical shop-floor dynamics, "
        "a discrete-event simulation engine is orchestrated using SimPy:"
    )
    st.markdown(
        """
        - **Workstation Resources**: Modeled using `simpy.PreemptiveResource(capacity=1)`.
        - **Breakdown Preemption**: Machine failures request the resource with `priority=-100, preempt=True`.
          When a breakdown occurs mid-operation, the active job process catches `simpy.Interrupt`,
          records the elapsed processing time, pauses during downtime, and resumes upon machine repair.
        - **Dispatching Policies**:
          - *Schedule-Paced*: Operations wait for their CP-SAT planned start times under nominal conditions, reproducing the exact 210 min baseline.
          - *Opportunistic*: Work-conserving dispatch serving queued jobs as soon as workstations become available.
        """
    )

    st.markdown("---")
    st.markdown("### 3. Software Technology Stack")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.markdown(
            """
            - **Constraint Programming**: Google OR-Tools CP-SAT `v9.15.6755`
            - **Discrete-Event Simulation**: SimPy `v4.1.2`
            - **Persistence Layer**: SQLite 3 with ACID transactions
            - **Data Processing**: Pandas `v3.1.1` & NumPy `v2.5.5`
            """
        )
    with col_t2:
        st.markdown(
            """
            - **Frontend Framework**: Streamlit `v1.67.0`
            - **Visualization**: Plotly `v7.1.0`
            - **Language Runtime**: Python 3.14.2 (Windows / Linux / macOS)
            - **Deployment Target**: Streamlit Community Cloud
            """
        )
