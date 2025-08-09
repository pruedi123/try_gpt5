from __future__ import annotations
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

# ---------- Month-based Helpers ----------
def first_of_month(d: date) -> date:
    return date(d.year, d.month, 1)

def add_months(d: date, m: int) -> date:
    y_total = d.year + (d.month - 1 + m) // 12
    m_total = (d.month - 1 + m) % 12 + 1
    from calendar import monthrange
    day = min(d.day, monthrange(y_total, m_total)[1])
    return date(y_total, m_total, day)

# ---------- Additional Age & Survivor Helpers ----------
def age_ym(dob: date, asof: date) -> tuple[int, int]:
    """Age in (years, months) at asof date (months 0-11)."""
    y = asof.year - dob.year
    m = asof.month - dob.month
    if asof.day < dob.day:
        m -= 1
    if m < 0:
        y -= 1
        m += 12
    return max(y, 0), max(m, 0)

def months_from_fra_at_date(p: 'Person', asof: date) -> int:
    """Months from FRA at a given date: positive if at/after FRA, negative if before."""
    age_y, age_m = age_ym(p.dob, asof)
    fra_y, fra_m = p.fra
    return months_between(age_y, age_m, fra_y, fra_m)

def survivor_annual(survivor: 'Person', decedent: 'Person', asof: date) -> float:
    """Simplified survivor benefit payable annually at `asof`.
    - Base = decedent's PIA with delayed credits if death after FRA; if death before FRA and not yet claimed, assume base = PIA (no early reduction).
    - Survivor receives up to 100% of base, reduced if survivor is claiming before survivor FRA.
    - Eligibility: survivor age >= 60. (Simplified; ignores child-in-care exceptions.)
    """
    # Must be at least age 60
    surv_age_y, surv_age_m = age_ym(survivor.dob, asof)
    if (surv_age_y * 12 + surv_age_m) < 60 * 12:
        return 0.0

    # Determine decedent base at death
    death_date = min(asof, safe_eol_date(decedent.dob, decedent.life_age))
    months_from_fra_dec_at_death = months_from_fra_at_date(decedent, death_date)
    if months_from_fra_dec_at_death >= 0:
        # delayed credits only (cap to 70)
        cap_months = min(months_from_fra_dec_at_death, (70 - decedent.fra[0]) * 12)
        base = retirement_adjustment(decedent.pia_at_fra, cap_months)
    else:
        # death prior to FRA and before claiming → approximate with PIA
        base = decedent.pia_at_fra

    # Apply survivor early-claim reduction if survivor is before FRA
    fra_y, fra_m = survivor.fra
    months_early = max(0, months_between(fra_y, fra_m, surv_age_y, surv_age_m))
    factor = survivor_reduction(months_early)
    return 12.0 * base * factor

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
        # Interpret input as "lives through life_age" → death occurs at the next birthday
        # Using life_age+1 ensures the final year (age == life_age) still receives payments
        return safe_eol_date(self.dob, self.life_age + 1)

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
        # Note: We interpret this as "they live THROUGH this age" (i.e., die right before the next birthday).
        # Implementation sets eol_date at birthday age = life_age+1 so benefits are paid through the full
        # year when they are age == life_age, with the month of death having no payment per SSA.
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
        eol = p.eol_date
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

        def worker_monthly_at_claim(p: Person) -> float:
            # Compute worker monthly benefit at claim, adjusted
            fra_y, fra_m = p.fra
            claim_y = p.claim_age_years
            claim_m = p.claim_age_months
            months_from_fra = months_between(claim_y, claim_m, fra_y, fra_m)
            return retirement_adjustment(p.pia_at_fra, months_from_fra)

        # Precompute EOLs and claim dates
        eol_map = {p.name: p.eol_date for p in people}
        claim_map = {p.name: p.claim_date for p in people}

        # Month utilities
        def months_between_firsts(a: date, b: date) -> int:
            """Whole months from first of month b to first of month a (a - b)."""
            return months_between(a.year, a.month, b.year, b.month)

        def clamp_months_in_year(start_month: date, end_month_excl: date, win_start: date, win_end_excl: date) -> int:
            """Count whole months in [win_start, win_end_excl) that overlap [start_month, end_month_excl)."""
            s = first_of_month(max(start_month, win_start))
            e = first_of_month(min(end_month_excl, win_end_excl))
            return max(0, months_between_firsts(e, s))

        # Build projection frame with Year column
        ss_rows = []
        start = date.today()
        for y in future_years:
            asof = add_years_months(start, y, 0)
            row = {"Year": y}
            # Own benefits (prorated by months in the year); for couples, stop own at spouse's death month
            own = {p.name: 0.0 for p in people}
            # Precompute each person's monthly-at-claim amount
            mo_at_claim = {p.name: worker_monthly_at_claim(p) for p in people}
            for idx, p in enumerate(people):
                year_start = first_of_month(asof)
                year_end_excl = first_of_month(add_years_months(asof, 1, 0))
                claim_first = first_of_month(claim_map[p.name])
                own_death_first = first_of_month(eol_map[p.name])
                # If paired, cap own window at spouse's death month (no double-pay with survivor months)
                if len(people) == 2:
                    other = people[1 - idx]
                    spouse_death_first = first_of_month(eol_map[other.name])
                    own_window_end = min(own_death_first, spouse_death_first)
                else:
                    own_window_end = own_death_first
                months_paid = clamp_months_in_year(claim_first, own_window_end, year_start, year_end_excl)
                own[p.name] = mo_at_claim[p.name] * months_paid

            # Spousal supplements (only while both alive and both filed; prorated by months)
            spousal = {p.name: 0.0 for p in people}
            if len(people) == 2:
                a, b = people[0], people[1]
                year_start = first_of_month(asof)
                year_end_excl = first_of_month(add_years_months(asof, 1, 0))
                # Months window when both are alive this year
                both_alive_end = min(first_of_month(eol_map[a.name]), first_of_month(eol_map[b.name]), year_end_excl)
                # A as spouse on B
                if claim_map[a.name] <= add_years_months(asof, 1, 0) and claim_map[b.name] <= add_years_months(asof, 1, 0):
                    base = max(0.0, spousal_base(b.pia_at_fra) - a.pia_at_fra)
                    # reduction only if A claimed before A's FRA
                    fra_y, fra_m = a.fra
                    months_early = max(0, -months_between(a.claim_age_years, a.claim_age_months, fra_y, fra_m))
                    sp_mo = base * spousal_reduction(months_early)
                    months_paid = clamp_months_in_year(first_of_month(max(claim_map[a.name], claim_map[b.name])), both_alive_end, year_start, year_end_excl)
                    spousal[a.name] = sp_mo * months_paid
                # B as spouse on A
                if claim_map[b.name] <= add_years_months(asof, 1, 0) and claim_map[a.name] <= add_years_months(asof, 1, 0):
                    base = max(0.0, spousal_base(a.pia_at_fra) - b.pia_at_fra)
                    fra_y, fra_m = b.fra
                    months_early = max(0, -months_between(b.claim_age_years, b.claim_age_months, fra_y, fra_m))
                    sp_mo = base * spousal_reduction(months_early)
                    months_paid = clamp_months_in_year(first_of_month(max(claim_map[a.name], claim_map[b.name])), both_alive_end, year_start, year_end_excl)
                    spousal[b.name] = sp_mo * months_paid

            # Start with totals from own + spousal
            total = {p.name: own[p.name] + spousal[p.name] for p in people}

            # Survivor logic (prorated): higher-of own vs survivor in month(s) after death, AND all months in years after death
            if len(people) == 2:
                a, b = people[0], people[1]
                year_start = first_of_month(asof)
                year_end_excl = first_of_month(add_years_months(asof, 1, 0))
                a_death = first_of_month(eol_map[a.name])
                b_death = first_of_month(eol_map[b.name])

                def add_survivor_months(surv: Person, dec: Person, dec_death_first: date):
                    # Case 1: decedent already dead before this year begins → survivor gets higher-of for the FULL year
                    if dec_death_first <= year_start:
                        months_surv = months_between_firsts(year_end_excl, year_start)
                        if months_surv > 0:
                            surv_mo_amt = survivor_annual(surv, dec, asof) / 12.0
                            own_mo_amt = mo_at_claim[surv.name]
                            higher = max(surv_mo_amt, own_mo_amt)
                            total[surv.name] += higher * months_surv
                        return
                    # Case 2: death occurs during this year → survivor begins the month AFTER death
                    if year_start < dec_death_first <= year_end_excl:
                        surv_start = add_months(dec_death_first, 1)
                        months_surv = max(0, months_between_firsts(year_end_excl, surv_start))
                        if months_surv > 0:
                            surv_mo_amt = survivor_annual(surv, dec, asof) / 12.0
                            own_mo_amt = mo_at_claim[surv.name]
                            higher = max(surv_mo_amt, own_mo_amt)
                            total[surv.name] += higher * months_surv

                # Apply for each possible decedent/survivor pairing
                add_survivor_months(a, b, b_death)
                add_survivor_months(b, a, a_death)

            # Append row with ages and benefits
            for p in people:
                age_now = compute_age(p.dob, add_years_months(date.today(), y, 0))
                row[f"{p.name} Age"] = age_now if age_now <= p.life_age else None
                row[f"{p.name} Own"] = round(own[p.name], 2) if own[p.name] > 0 else None
                row[f"{p.name} Spousal"] = round(spousal[p.name], 2) if spousal[p.name] > 0 else None
                row[f"{p.name} Total SS"] = round(total[p.name], 2) if total[p.name] > 0 else None
            row["Household Total SS"] = round(sum(total.values()), 2)
            ss_rows.append(row)

        if ss_rows:
            ss_df = pd.DataFrame(ss_rows)
            # Always show years as rows (not transposed), as requested
            st.dataframe(ss_df, hide_index=True, use_container_width=True)
        else:
            st.info("No Social Security rows to display (check claim ages and life expectancy).")

    st.caption(
        "Notes: Current age is calculated from today’s date and the DOB. "
        "End-of-life date reflects the interpretation that a person lives THROUGH the entered age (death occurs just before the next birthday). "
        "Social Security calculations use simplified but realistic monthly rules: no benefit is payable for the month of death; spousal benefits stop at death; survivor benefits begin the month after death if the survivor is age-eligible; early-claim reductions and delayed credits apply, with delayed credits capped at age 70."
    )
else:
    st.info("Use the sidebar to add at least one person.")