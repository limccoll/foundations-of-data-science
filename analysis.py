"""UK Power Grid During COVID-19.

Research question: how did lockdowns affect electricity demand in the UK?
Data: gridwatch.templar.co.uk, five-minute readings, 2019-2022.

Usage:
    python analysis.py data/gridwatch.csv
"""
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from scipy import stats

warnings.filterwarnings("ignore")

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/gridwatch.csv")
FIG = Path(__file__).parent / "figures"
FIG.mkdir(exist_ok=True)

# Colour-blind safe palette, text readable at 8pt+ in the PDF report
sns.set_palette("colorblind")
sns.set_style("whitegrid")
plt.rcParams.update({"font.size": 10, "axes.labelsize": 10, "axes.titlesize": 12,
                     "xtick.labelsize": 9, "ytick.labelsize": 9, "legend.fontsize": 9})

# ---------------------------------------------------------------- load and clean
df = pd.read_csv(DATA)
df.columns = df.columns.str.strip()          # some column names have spaces
df["timestamp"] = pd.to_datetime(df["timestamp"])
df = df.drop(columns="id", errors="ignore").sort_values("timestamp").reset_index(drop=True)
print(f"Loaded {len(df):,} rows: {df['timestamp'].min()} to {df['timestamp'].max()}")

# UK demand never really drops below ~15,000 MW, so lower readings are sensor errors
outliers = df["demand"] < 15000
print(f"Removing {outliers.sum()} outlier rows (demand < 15,000 MW)")
df = df[~outliers].reset_index(drop=True)

# ---------------------------------------------------------------- lockdown periods (gov.uk timeline)
LOCKDOWNS = [
    ("2020-03-23", "2020-07-04"),
    ("2020-11-05", "2020-12-02"),
    ("2021-01-06", "2021-03-08"),
]
LOCKDOWNS = [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in LOCKDOWNS]
first_start, last_end = LOCKDOWNS[0][0], LOCKDOWNS[-1][1]

df["lockdown"] = False
for start, end in LOCKDOWNS:
    df["lockdown"] |= df["timestamp"].between(start, end)

PRE, LOCK, BETWEEN, POST = ("Pre-COVID (2019-Q1 2020)", "Lockdown",
                            "Between Lockdowns", "Post-Lockdown (2021-2022)")
PERIOD_ORDER = [PRE, LOCK, BETWEEN, POST]
df["period"] = BETWEEN
df.loc[df["timestamp"] < first_start, "period"] = PRE
df.loc[df["timestamp"] > last_end, "period"] = POST
df.loc[df["lockdown"], "period"] = LOCK

df["fossil_fuels"] = df["ccgt"] + df["coal"]          # gas + coal
df["renewables"] = df["wind"] + df["solar"]
df["renewable_pct"] = df["renewables"] / df["demand"] * 100
df["date"] = df["timestamp"].dt.normalize()

# Five-minute data is too noisy for trends, so also build daily averages
daily = df.groupby("date").agg(demand=("demand", "mean")).reset_index()

# ---------------------------------------------------------------- results
summary = (df.groupby("period")[["demand", "renewables", "fossil_fuels", "renewable_pct"]]
             .mean().reindex(PERIOD_ORDER).round(1))
print("\nAverages by period:\n", summary)

pre = df.loc[df["period"] == PRE, "demand"]
lock = df.loc[df["period"] == LOCK, "demand"]
pct = (lock.mean() - pre.mean()) / pre.mean() * 100
# Sample 10,000 readings from each period for the two-sample t-test
t, p = stats.ttest_ind(pre.sample(min(10000, len(pre)), random_state=42),
                       lock.sample(min(10000, len(lock)), random_state=42))
print(f"\nPre-COVID {pre.mean():,.0f} MW vs lockdown {lock.mean():,.0f} MW "
      f"({pct:+.2f}%), t = {t:.2f}, p = {p:.2e}")

# ---------------------------------------------------------------- Figure 1: periods compared
short = ["Pre-COVID", "Lockdown", "Between", "Post"]
fig, axes = plt.subplots(1, 3, figsize=(14, 5))
panels = [("demand", "Average Demand (MW)", "Demand by Period", "C0", "{:.0f}"),
          ("renewable_pct", "Renewable Share (%)", "Renewables as % of Demand", "C2", "{:.1f}%"),
          ("fossil_fuels", "Fossil Fuel Generation (MW)", "Gas + Coal Generation", "C3", "{:.0f}")]
for ax, (col, ylabel, title, colour, fmt) in zip(axes, panels):
    values = summary[col].values
    bars = ax.bar(short, values, color=colour)
    ax.bar_label(bars, labels=[fmt.format(v) for v in values], fontsize=9)
    ax.set_ylabel(ylabel); ax.set_title(title); ax.tick_params(axis="x", rotation=45)
fig.tight_layout(); fig.savefig(FIG / "figure1_period_comparison.png", dpi=300)

# ---------------------------------------------------------------- Figure 2: 7-day rolling average
daily["demand_7day"] = daily["demand"].rolling(7, center=True).mean()
fig, ax = plt.subplots(figsize=(12, 6))
ax.plot(daily["date"], daily["demand_7day"], linewidth=1.5, label="7-day average demand")
names = ["Lockdown 1 (Mar-Jul 2020)", "Lockdown 2 (Nov-Dec 2020)", "Lockdown 3 (Jan-Mar 2021)"]
for (start, end), name in zip(LOCKDOWNS, names):
    ax.axvspan(start, end, alpha=0.2, color="red", label=name)
ax.set_xlabel("Date"); ax.set_ylabel("Electricity Demand (MW)")
ax.set_title("UK Electricity Demand During COVID-19 Lockdowns (2019-2022)")
ax.legend(loc="upper right")
fig.tight_layout(); fig.savefig(FIG / "figure2_demand_timeseries.png", dpi=300)

# ---------------------------------------------------------------- Figure 3: generation mix
sources = [("wind", "Wind"), ("solar", "Solar"), ("nuclear", "Nuclear"),
           ("ccgt", "Gas (CCGT)"), ("french_ict", "Imports (France)")]
monthly = df.set_index("timestamp")[[s for s, _ in sources]].resample("MS").mean()
fig, ax = plt.subplots(figsize=(12, 6))
ax.stackplot(monthly.index, *[monthly[s] for s, _ in sources],
             labels=[n for _, n in sources], alpha=0.8)
for x in (first_start, last_end):
    ax.axvline(x, color="red", linestyle="--", linewidth=1, alpha=0.5)
ax.text(first_start, ax.get_ylim()[1] * 0.95, "Lockdowns", color="red", fontsize=9, va="top")
ax.set_xlabel("Date"); ax.set_ylabel("Power Generation (MW)")
ax.set_title("UK Electricity Generation Mix by Source (2019-2022)")
ax.legend(loc="upper left")
fig.tight_layout(); fig.savefig(FIG / "figure3_energy_mix.png", dpi=300)
print(f"\nSaved figures to {FIG}")
