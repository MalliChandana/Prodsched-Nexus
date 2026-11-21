# ProdSched Nexus

**A Disruption-Aware Workshop Production Scheduling Engine Using Constraint Programming and Discrete-Event Simulation**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![OR-Tools](https://img.shields.io/badge/OR--Tools-CP--SAT-orange.svg)](https://developers.google.com/optimization)
[![SimPy](https://img.shields.io/badge/SimPy-DES-green.svg)](https://simpy.readthedocs.io/)
[![Streamlit](https://img.shields.io/badge/Streamlit-UI-red.svg)](https://streamlit.io/)
[![Tests Passing](https://img.shields.io/badge/tests-20%20passed-brightgreen.svg)]()

---

## 1. Executive Overview

**ProdSched Nexus** is a functional, deployment-ready academic and industrial manufacturing scheduling engine. It integrates **Exact Constraint Programming (Google OR-Tools CP-SAT)** with **Discrete-Event Simulation (SimPy)** and interactive **Plotly analytics** wrapped in a modern industrial **Streamlit** user interface.

The system plans workshop job-shop schedules, simulates realistic shop-floor execution, and responds dynamically to real-world manufacturing disruptions:
- **Unplanned Machine Breakdowns** (preemption, machine repair windows, downtime tracking).
- **Urgent Customer Orders** (rush order insertion, priority weighting, schedule re-solving).
- **Processing Time Variations & Delays** (tool wear, hard materials, downstream ripple effects).

---

## 2. System Architecture

```text
ProdSched-Nexus/
│
├── app.py                      # Streamlit Enterprise Industrial UI (8 Modules)
├── scheduler.py                # Google OR-Tools CP-SAT Job-Shop Optimizer
├── disruption.py               # Disruption Management & Rescheduling Engine
├── simulator.py                # SimPy Discrete-Event Simulation (DES) Engine
├── data_manager.py             # Workshop Data Models, CSV Handler & Validation
├── analytics.py                # Performance KPIs & Interactive Plotly Gantt Charts
├── database.py                 # SQLite Persistent Storage for Schedules & Events
├── requirements.txt            # Application Dependencies
├── README.md                   # Complete Documentation
├── .gitignore                  # Git Ignore Configuration
│
├── data/
│   ├── production_jobs.csv     # Canonical Workshop Dataset (5 Jobs, 13 Operations)
│   └── prodsched_nexus.db      # SQLite Persistence Database
│
├── tests/
│   ├── test_scheduler.py       # Baseline OR-Tools CP-SAT Verification (5 Tests)
│   ├── test_disruption.py      # Breakdowns, Urgent Orders & Delay Tests (4 Tests)
│   ├── test_simulator.py       # SimPy Preemption, Sequence & Timing Tests (5 Tests)
│   └── test_analytics.py       # Utilization, Tardiness & KPI Tests (6 Tests)
│
└── assets/
    └── logo.png                # Official Application Logo
```

---

## 3. Mathematical & Optimization Formulation

### Job-Shop Scheduling Problem with Machine Downtime Intervals
- **Jobs**: Set $J = \{J_1, \dots, J_n\}$. Each job $j$ has an ordered chain of operations $O_{j,1} \prec O_{j,2} \prec \dots \prec O_{j,m_j}$.
- **Machines**: Set $M = \{CUT, DRL, FIN, \dots\}$. Each operation requires an assigned machine $m(O_{j,k})$ for fixed duration $p_{j,k}$.
- **Precedence**: $S_{j, k+1} \ge S_{j,k} + p_{j,k} \quad \forall j, k$
- **Disjunctive Machine Allocation**: No two operations may simultaneously occupy the same machine:
  $$\text{NoOverlap}\left(\{I_{j,k} \mid m(O_{j,k}) = m\} \cup \{I_{\text{breakdown}, m}\}\right)$$
- **Machine Downtime Interval**: A breakdown on machine $m$ over interval $[\tau_{\text{start}}, \tau_{\text{start}} + \tau_{\text{dur}})$ is represented as a fixed interval variable within that machine's `NoOverlap` constraint, ensuring operations cannot overlap the repair window.
- **Objective Function**:
  $$\min C_{\max} = \max_{j \in J} (S_{j, m_j} + p_{j, m_j})$$

### Discrete-Event Simulation (DES) Architecture
- **SimPy Environment**: Time-stepped discrete-event model.
- **Preemptive Resources**: Workstations are modeled using `simpy.PreemptiveResource(capacity=1)`.
- **Breakdown Handling**: Injected with `priority=-100, preempt=True`. If an operation is running when a breakdown occurs, SimPy interrupts the process, records elapsed time, and resumes the remaining processing duration upon recovery.
- **Dispatching Strategy**: Supports **Schedule-Paced Dispatch** (strictly preserves CP-SAT timetable in nominal conditions) and **Opportunistic Dispatch** (work-conserving).

---

## 4. Key Application Modules

1. **Production Dashboard**: High-level KPI cards (Total Jobs, Machines, Completed, In-Production, Pending, Original Makespan, Revised Makespan, Avg Utilization, Downtime, Delayed Orders), machine status overview, active schedule timetable, and recent disruption feeds.
2. **Job Management**: Complete order management. Add, edit, delete, search, and filter production orders. Dynamic multi-operation routing editor. Input validation. Reset to canonical dataset.
3. **Machine Management**: Workstation overview (Cutting, Drilling, Finishing), operational status toggle (`Operational`, `Maintenance`, `Breakdown`, `Idle`), workload distribution, busy/downtime breakdown, and new machine onboarding.
4. **Schedule Optimizer**: Full CP-SAT solver controls (time limit, random seed, objective weighting), makespan metrics, optimality gap, theoretical lower bounds, and downloadable CSV timetable.
5. **Disruption Center**: Dedicated disruption command center for:
   - *Scenario A*: Machine Breakdown (machine selection, start minute, duration, reason).
   - *Scenario B*: Urgent Order Insertion (high priority, prompt delivery, custom routing).
   - *Scenario C*: Processing Delays (operation selection, added duration, cause).
   - Instant re-optimization, diagnostic impact report, and Before-vs-After Gantt comparisons.
6. **Production Simulation**: SimPy discrete-event engine. Real-time event log, stochastic duration variation (±5%), queue wait-time tracking, breakdown preemption verification, and event log CSV export.
7. **Analytics & Reports**:
   - Machine utilization stacked bar chart (`Busy`, `Downtime`, `Idle`).
   - Job cycle time breakdown (`Processing` vs `Waiting`).
   - Delivery due date vs completion tardiness chart.
   - Makespan comparison (`Baseline` vs `Revised` vs `SimPy`).
   - One-click full CSV report download.
8. **System Information**: Mathematical formulation, algorithm parameters, technology stack details, and academic citation.

---

## 5. Canonical Sample Data (Phase 1 Baseline)

The canonical workshop comprises 3 machines and 5 jobs (13 operations):
- **Cutting Machine (CUT)**: Bandsaw station.
- **Drilling Machine (DRL)**: Drill press for holes, bores, and patterns.
- **Finishing Machine (FIN)**: Deburring and surface finishing station.

### Optimal Baseline Verification
Under nominal conditions, Google OR-Tools CP-SAT proves an **optimal baseline makespan of 210 minutes**:
- `J-101` (Support Bracket): CUT (45m) $\rightarrow$ DRL (30m) $\rightarrow$ FIN (20m)
- `J-102` (Drive Shaft): CUT (60m) $\rightarrow$ DRL (40m) $\rightarrow$ FIN (25m)
- `J-103` (Gear Blank): CUT (55m) $\rightarrow$ FIN (35m) $\rightarrow$ DRL (22m)
- `J-104` (Cover Panel): DRL (28m) $\rightarrow$ FIN (32m)
- `J-105` (Cast Flange): FIN (24m) $\rightarrow$ DRL (36m)

---

## 6. Installation & Local Execution

### Prerequisites
- Python 3.10, 3.11, 3.12, 3.13, or 3.14
- Git

### Local Setup
```bash
# 1. Clone repository
git clone https://github.com/<your-username>/ProdSched-Nexus.git
cd ProdSched-Nexus

# 2. Create and activate virtual environment
python -m venv .venv

# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Run Automated Test Suite
```bash
python -m unittest discover -s tests
```
*Expected Output: `Ran 20 tests in ~0.75s ... OK`.*

### Launch the Streamlit Application
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

---

## 7. Step-by-Step Demonstration Workflows

### How to Demonstrate a Machine Breakdown
1. Open the application and navigate to **Disruption Center**.
2. Select **Scenario A: Machine Breakdown**.
3. Choose **Cutting (CUT)**, set **Start Time = 50 min**, **Duration = 40 min**, and Reason = *"Motor Bearing Failure"*.
4. Click **Inject Breakdown & Recalculate Schedule**.
5. Observe the automated impact analysis:
   - Revised makespan increases from 210 min to 250 min (+40 min).
   - Gantt chart displays the red hatched breakdown block on Cutting from 50 to 90 min.
   - Operations on Cutting (`J-102`, `J-101`) are automatically pushed past 90 min without any overlaps.

### How to Demonstrate an Urgent Order
1. Navigate to **Disruption Center** $\rightarrow$ **Scenario B: Urgent Production Order**.
2. Set Job ID = `J-RUSH-1`, Priority = `1`, Due Date = `120 min`.
3. Click **Insert Urgent Order & Recalculate Schedule**.
4. Observe the revised schedule accommodates the new order with high priority while minimizing delays across other jobs.

### How to Run the Discrete-Event Simulation
1. Navigate to **Production Simulation**.
2. Select **Schedule-Paced (Tracks CP-SAT Timetable)** or **Opportunistic**.
3. Click **Run Discrete-Event Simulation**.
4. Review the simulated makespan, queue waiting times, and detailed event log table showing every `JOB_ARRIVED`, `OP_QUEUED`, `OP_STARTED`, and `JOB_COMPLETED` transition.

---

## 8. Deployment to Streamlit Community Cloud

1. Push your repository to GitHub:
   ```bash
   git add .
   git commit -m "Complete ProdSched Nexus enterprise release"
   git push origin main
   ```
2. Go to [share.streamlit.io](https://share.streamlit.io) and log in with GitHub.
3. Click **New app**.
4. Select your repository: `<your-username>/ProdSched-Nexus`.
5. Set Main file path: `app.py`.
6. Click **Deploy!**

---

## 9. Automated Testing Summary

| Test Module | Coverage Area | Number of Tests | Status |
| :--- | :--- | :---: | :---: |
| `tests/test_scheduler.py` | CP-SAT Job-Shop formulation, 210m baseline, precedence, no-overlap | 5 | **PASSED** |
| `tests/test_disruption.py` | Breakdown downtime intervals, urgent order injection, delay shifts | 4 | **PASSED** |
| `tests/test_simulator.py` | SimPy DES routing, machine preemption, event lifecycle, metrics | 5 | **PASSED** |
| `tests/test_analytics.py` | Utilization formula $(Busy / Available) \times 100$, tardiness, KPI exports | 6 | **PASSED** |
| **Total** | **End-to-End Suite** | **20** | **PASSED** |

---

## 10. License & Academic Attribution
Developed for research and education in Operations Research, Industrial Engineering, and Discrete-Event Simulation.
Built with Google OR-Tools and SimPy.
