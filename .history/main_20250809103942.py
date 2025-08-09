from datetime import date, datetime
from dataclasses import dataclass
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Household Longevity", layout="centered")

# ---------- Helpers ----------
def compute_age(dob: date, today: date | None = None) -> int:
    if today is None:
        today = date.today()
    years = today.year - dob.year
    # If birthday hasn't occurred yet this year, subtract one
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return max(years, 0)

def safe_eol_date(dob: date, life_age: int) -> date:
    """Return the birthday on which the person turns `life_age`.
    If the birthday does not exist in that year (e.g., Feb 29 on a non-leap year),
    fallback to the last valid day of that month."""
    year = dob.year + life_age
    try:
        return date(year, dob.month, dob.day)
    except ValueError:
        # Handle invalid dates (e.g., Feb 29 on non-leap year)
        # Find last day of the month
        from calendar import monthrange
        last_day = monthrange(year, dob.month)[1]
        return date(year, dob.month, last_day)

# ---------- Social Security Helpers ----------
from math import floor

def fra_for_birth_year(y: int) -> tuple[int, int]:
    """Return Full Retirement Age (years, months) per SSA schedule for retirement/spousal benefits."""
    if y <= 1937:
        return 65, 0
    if 1938 <= y <= 1942:
        return 65, (y - 1937) * 2
    if 1943 <= y <= 1954:
        return 66, 0
    if 1955 <= y <= 1959:
        return 66, (y - 1954) * 2
    if y >= 1960:
        return 67, 0
    return 67, 0

def months_between(yrs_a: int, mos_a: int, yrs_b: int, mos_b: int) -> int:
    return (yrs_a * 12 + mos_a) - (yrs_b * 12 + mos_b)

def retirement_adjustment(pia: float, months_from_fra: int) -> float:
    """Compute worker retirement benefit at claim age given PIA and months_from_fra.
    Positive months = claimed after FRA (delayed credits at 2/3% per month up to age 70).
    Negative months = claimed before FRA (reduction: 5/9% per month for first 36, then 5/12% beyond)."""
    if months_from_fra == 0:
        return pia
    if months_from_fra < 0:
        m = -months_from_fra
        first = min(m, 36)
        extra = max(m - 36, 0)
        reduction = first * (5/900) + extra * (5/1200)  # 5/9% and 5/12% per month
        factor = max(0.0, 1.0 - reduction)
        return pia * factor
    # delayed credits
    # cap at age 70: max months after FRA considered
    return pia * (1.0 + (2/300) * min(months_from_fra, 12 * 4))  # 2/3% per month

def spousal_base(pia_worker: float) -> float:
    """Max spousal benefit base = 50% of worker's PIA."""
    return 0.5 * pia_worker

def spousal_reduction(months_early: int) -> float:
    """Spousal reduction if spouse files before *their* FRA.
    First 36 months: 25/36% per month; beyond: 5/12% per month."""
    if months_early <= 0:
        return 1.0
    first = min(months_early, 36)
    extra = max(months_early - 36, 0)
    reduction = first * (25/3600) + extra * (5/1200)
    return max(0.0, 1.0 - reduction)

def survivor_reduction(months_early: int) -> float:
    """Approx survivor reduction: max 28.5% reduction if claimed at 60.
    Use linear 0.396%/mo up to 57 months (for FRA=66) or 82 months (for FRA=67)."""
    if months_early <= 0:
        return 1.0
    return max(0.715, 1.0 - months_early * 0.00396)

def add_years_months(d: date, y: int, m: int) -> date:
    """Add years and months to a date clamping to month-end if needed."""
    y_total = d.year + y + (d.month - 1 + m) // 12
    m_total = (d.month - 1 + m) % 12 + 1
    from calendar import monthrange
    day = min(d.day, monthrange(y_total, m_total)[1])
    return date(y_total, m_total, day)

# ---------- Person Dataclass ----------
@dataclass
class Person:
    name: str
    dob: date
    life_age: int
    claim_age_years: int = 67
    claim_age_months: int = 0
    pia_at_fra: float = 0.0  # Monthly benefit at FRA (PIA)

    @property
    def age(self) -> int:
        return compute_age(self.dob)

    @property
    def fra(self) -> tuple[int, int]:
        return fra_for_birth_year(self.dob.year)

    @property
    def claim_date(self) -> date:
        return add_years_months(self.dob, self.claim_age_years, self.claim_age_months)

    @property
    def years_remaining(self) -> int:
        return max(self.life_age - self.age, 0)

    @property
    def eol_date(self) -> date:
        return safe_eol_date(self.dob, self.life_age)

# ---------- Sidebar Inputs ----------
st.title("Household Ages & Life Expectancy")

st.sidebar.header("People")
n_people = st.sidebar.number_input("How many people?", min_value=1, max_value=6, value=2, step=1)

people: list[Person] = []
for i in range(int(n_people)):
    with st.sidebar.expander(f"Person {i+1}", expanded=(i == 0)):
        name = st.text_input(f"Name {i+1}", key=f"name_{i}")
        dob = st.date_input(
            f"Date of Birth {i+1}",
            value=date(1940, 1, 1),
            max_value=date.today(),
            key=f"dob_{i}",
        )
        life_age = st.number_input(
            f"Life expectancy (they will live through) {i+1}",
            min_value=50, max_value=120, value=95, step=1, key=f"life_{i}"
        )
        claim_age_y = st.number_input(
            f"Claim Age — years {i+1}", min_value=62, max_value=70, value=67, step=1, key=f"claimy_{i}"
        )
        claim_age_m = st.number_input(
            f"Claim Age — months {i+1}", min_value=0, max_value=11, value=0, step=1, key=f"claimm_{i}"
        )
        pia = st.number_input(
            f"Benefit at FRA (monthly PIA) {i+1}", min_value=0.0, value=3000.0, step=50.0, key=f"pia_{i}"
        )
        if name.strip():
            people.append(
                Person(
                    name=name.strip(),
                    dob=dob,
                    life_age=int(life_age),
                    claim_age_years=int(claim_age_y),
                    claim_age_months=int(claim_age_m),
                    pia_at_fra=float(pia),
                )
            )

# ---------- Output Table ----------
if people:
    rows = []
    today = date.today()
    for p in people:
        age_now = compute_age(p.dob, today)
        eol = safe_eol_date(p.dob, p.life_age)
        years_left = max(p.life_age - age_now, 0)
        rows.append({
            "Name": p.name,
            "DOB": p.dob.strftime("%Y-%m-%d"),
            "Current Age": age_now,
            "Life Expectancy": p.life_age,
            "Years Remaining": years_left,
            "End-of-Life Date": eol.strftime("%Y-%m-%d"),
            "Claim Age (y:m)": f"{p.claim_age_years}:{p.claim_age_months:02d}",
            "FRA (y:m)": f"{p.fra[0]}:{p.fra[1]:02d}",
            "PIA @ FRA (monthly)": round(p.pia_at_fra, 2),
        })

        if p.life_age < age_now:
            st.sidebar.warning(f"⚠️ {p.name}: life expectancy ({p.life_age}) is below current age ({age_now}).")

    df = pd.DataFrame(rows)
    st.subheader("Summary")
    st.dataframe(df, hide_index=True, use_container_width=True)

    # ---- Ages by Future Year (row 1 .. max remaining years) ----
    if not df.empty:
        max_years = int(df["Years Remaining"].max())
        if max_years > 0:
            future_years = list(range(1, max_years + 1))

            # Build a column per person with ages each future year; blank after life age
            ages_by_year = {}
            for _, r in df.iterrows():
                name = r["Name"]
                age_now = int(r["Current Age"])
                life_age = int(r["Life Expectancy"])
                series = []
                for y in future_years:
                    age_at = age_now + y
                    series.append(age_at if age_at <= life_age else None)
                ages_by_year[name] = series

            future_df = pd.DataFrame({"Year": future_years})
            for name, series in ages_by_year.items():
                future_df[name] = series

            # Transpose so years become columns and people become rows
            future_df = future_df.set_index("Year").T.reset_index().rename(columns={"index": "Name"})

            st.subheader("Ages by Future Year")
            st.dataframe(future_df, hide_index=True, use_container_width=True)
        else:
            st.info("No future years to display — all entries have zero years remaining.")

    # ---- Social Security Projection (Annual, no COLA; illustrative rules) ----
    if len(people) >= 1:
        st.subheader("Social Security — Annual Projection (no COLA)")

        max_years = int(df["Years Remaining"].max())
        future_years = list(range(1, max_years + 1)) if max_years > 0 else []

        def worker_annual(p: Person, asof_date: date) -> float:
            # Compute worker monthly benefit at claim, adjusted, then convert to annual
            fra_y, fra_m = p.fra
            # months from FRA at claim
            claim_y = p.claim_age_years
            claim_m = p.claim_age_months
            months_from_fra = months_between(claim_y, claim_m, fra_y, fra_m)
            monthly_at_claim = retirement_adjustment(p.pia_at_fra, months_from_fra)
            # Payable only once asof_date >= claim_date
            return 12.0 * monthly_at_claim if asof_date >= p.claim_date else 0.0

        # Precompute EOLs and claim dates
        eol_map = {p.name: p.eol_date for p in people}
        claim_map = {p.name: p.claim_date for p in people}

        # Build projection frame with Year column
        ss_rows = []
        start = date.today()
        for y in future_years:
            asof = add_years_months(start, y, 0)
            row = {"Year": y}
            # Compute who is alive
            alive = {p.name: (asof <= eol_map[p.name]) for p in people}

            # Own benefits
            own = {}
            for p in people:
                own[p.name] = worker_annual(p, asof) if alive[p.name] else 0.0

            # Spousal supplements (simple: if both alive and both have filed, spouse can receive up to 50% of worker's PIA minus their own PIA; reduced if spouse files before FRA)
            spousal = {p.name: 0.0 for p in people}
            if len(people) == 2:
                a, b = people[0], people[1]
                # A as spouse on B
                if alive[a.name] and alive[b.name] and asof >= claim_map[a.name] and asof >= claim_map[b.name]:
                    base = max(0.0, spousal_base(b.pia_at_fra) - a.pia_at_fra)
                    # months early relative to A's FRA at A's claim age
                    fra_y, fra_m = a.fra
                    months_early = months_between(fra_y, fra_m, a.claim_age_years, a.claim_age_months)
                    # months_early>0 means claimed after FRA; reduction only for early
                    months_early = max(0, -months_between(a.claim_age_years, a.claim_age_months, fra_y, fra_m))
                    spousal[a.name] = 12.0 * base * spousal_reduction(months_early)
                # B as spouse on A
                if alive[b.name] and alive[a.name] and asof >= claim_map[b.name] and asof >= claim_map[a.name]:
                    base = max(0.0, spousal_base(a.pia_at_fra) - b.pia_at_fra)
                    fra_y, fra_m = b.fra
                    months_early = max(0, -months_between(b.claim_age_years, b.claim_age_months, fra_y, fra_m))
                    spousal[b.name] = 12.0 * base * spousal_reduction(months_early)

            # Survivor switch: if one has died by this year and the other is alive, survivor gets the decedent's *actual* benefit if larger than their current total (own+spousal)
            total = {p.name: own[p.name] + spousal[p.name] for p in people}
            if len(people) == 2:
                a, b = people[0], people[1]
                # Determine decedent(s) this year
                a_alive, b_alive = alive[a.name], alive[b.name]
                if a_alive and not b_alive:
                    # B deceased; survivor benefit for A is max(A total, B total at death)
                    total_b_at_death = worker_annual(b, min(asof, eol_map[b.name]))
                    total[a.name] = max(total[a.name], total_b_at_death)
                if b_alive and not a_alive:
                    total_a_at_death = worker_annual(a, min(asof, eol_map[a.name]))
                    total[b.name] = max(total[b.name], total_a_at_death)

            # Append row with ages and benefits
            for p in people:
                age_now = compute_age(p.dob, add_years_months(date.today(), y, 0))
                row[f"{p.name} Age"] = age_now if alive[p.name] else None
                row[f"{p.name} Own"] = round(own[p.name], 2) if alive[p.name] else None
                row[f"{p.name} Spousal"] = round(spousal[p.name], 2) if alive[p.name] else None
                row[f"{p.name} Total SS"] = round(total[p.name], 2) if alive[p.name] else None
            row["Household Total SS"] = round(sum(v for v in total.values() if v), 2)
            ss_rows.append(row)

        if ss_rows:
            ss_df = pd.DataFrame(ss_rows)
            # Always show years as rows (not transposed), as requested
            st.dataframe(ss_df, hide_index=True, use_container_width=True)
        else:
            st.info("No Social Security rows to display (check claim ages and life expectancy).")

    st.caption(
        "Notes: Current age is calculated from today’s date and the DOB. "
        "End-of-life date is the birthday on which the person reaches the life expectancy age. "
        "Social Security calculations use simplified SSA rules: early-claim reductions, delayed credits, spousal supplements, and a basic survivor swap."
    )
else:
    st.info("Use the sidebar to add at least one person.")