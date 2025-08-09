from __future__ import annotations

# ───────────────────────────────────────────────────────────────────────
# App & Imports
# ───────────────────────────────────────────────────────────────────────
from datetime import date, datetime
import re
import pandas as pd
import streamlit as st

# Helper: robustly parse DOB strings as day/month/year
# Accepts: 05/11/1958, 5-11-58, 5 11 1958, 05.11.1958
# Prefers D/M/Y, but will fall back to M/D/Y if needed (and unambiguous)
def _parse_dob_ddmmyyyy(s: str):
    s = (s or "").strip()
    if not s:
        raise ValueError("Empty DOB")
    from datetime import datetime as _dt

    # Normalize separators to '/'
    s_norm = re.sub(r"[.\-\s]+", "/", s)
    s_norm = re.sub(r"/+", "/", s_norm)

    # First try clear D/M/Y patterns
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return _dt.strptime(s_norm, fmt).date()
        except ValueError:
            pass

    # If that fails, attempt smart fallback when user typed M/D/Y
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s_norm)
    if not m:
        raise ValueError("Invalid DOB format")
    a, b, c = m.groups()
    dd = int(a)
    mm = int(b)
    yyyy = int(c)
    if yyyy < 100:
        yyyy += 2000 if yyyy <= 68 else 1900  # mimic datetime behavior

    # If dd>12 and mm<=12, it's clearly D/M/Y but day wasn't two-digit parsed above (e.g., '31/1/1958')
    # Or if dd<=31 and mm>12, it's probably M/D/Y where user swapped; swap them.
    if mm > 12 and dd <= 12:
        # Looks like M/D entered where we expect D/M; swap
        dd, mm = mm, dd
    # Validate ranges
    if not (1 <= dd <= 31 and 1 <= mm <= 12):
        raise ValueError("Invalid day or month in DOB")

    # Build a date safely (handle month lengths)
    try:
        return _dt.strptime(f"{dd:02d}/{mm:02d}/{yyyy:04d}", "%d/%m/%Y").date()
    except ValueError:
        raise ValueError("Invalid calendar date in DOB")

# Pull the data model and calculators from ss.py
from ss import (
    Person,
    compute_age,
    project_social_security,
)

st.set_page_config(page_title="Household Longevity", layout="centered")

# Session state: gate heavy calculations until user clicks Calculate
if "do_calc" not in st.session_state:
    st.session_state["do_calc"] = False

#
# ═══════════════════════════════════════════════════════════════════════
# SECTION: Streamlit Sidebar Inputs
# ═══════════════════════════════════════════════════════════════════════
st.title("Household Ages & Life Expectancy")

st.sidebar.header("People")
n_people = st.sidebar.number_input("How many people?", min_value=1, max_value=6, value=2, step=1)

# Action buttons
calc_col, reset_col = st.sidebar.columns(2)
with calc_col:
    if st.button("Calculate", type="primary"):
        st.session_state["do_calc"] = True
with reset_col:
    if st.button("Clear", help="Clear results so changes don't auto-calc"):
        st.session_state["do_calc"] = False

people: list[Person] = []

# ── BASIC INFO (for all people) ───────────────────────────────────────
st.sidebar.markdown("### Basic Info (Name, DOB, Life Expectancy)")
basic_info: list[dict] = []
for i in range(int(n_people)):
    with st.sidebar.expander(f"Person {i+1} — Basic Info", expanded=(i == 0)):
        # Defaults for first two people
        if i == 0:
            _def_name = "Paul"
            _def_dob_str = "11/06/1959"  # dd/mm/yyyy → 11 June 1959
            _def_life = 85
        elif i == 1:
            _def_name = "Cindy"
            _def_dob_str = "05/22/1960"  # dd/mm/yyyy → 22 May 1960
            _def_life = 95
        else:
            _def_name = ""
            _def_dob_str = "01/01/1940"
            _def_life = 95

        name = st.text_input(f"Name {i+1}", value=_def_name, key=f"name_{i}")
        dob_str = st.text_input(
            f"Date of Birth {i+1} (dd/mm/yyyy)",
            value=_def_dob_str,
            key=f"dob_{i}_str",
            help="Enter day/month/year, e.g., 05/11/1958"
        )
        # Parse DOB in dd/mm/yyyy (also accepts d-m-yyyy and d/m/yy)
        dob = None
        dob_error = None
        try:
            dob = _parse_dob_ddmmyyyy(dob_str)
            if dob > date.today():
                st.warning("DOB is in the future—please correct.")
            else:
                st.caption(f"Parsed DOB → {dob.strftime('%d/%m/%Y')} (ISO {dob.isoformat()})")
        except ValueError as e:
            dob_error = str(e)
            st.error(f"Could not parse DOB '{dob_str}'. Enter as day/month/year, e.g., 05/11/1958 (also accepts 5-11-58).")
        life_age = st.number_input(
            f"Life expectancy (they will live through) {i+1}",
            min_value=50, max_value=120, value=int(_def_life), step=1, key=f"life_{i}"
        )
        basic_info.append({
            "name": name.strip(),
            "dob": dob,
            "life_age": int(life_age),
            "dob_error": dob_error,
        })

# ── SOCIAL SECURITY CLAIMING (for all people) ─────────────────────────
st.sidebar.markdown("### Social Security Claiming (for all)")
claim_info: list[dict] = []
for i in range(int(n_people)):
    with st.sidebar.expander(f"Person {i+1} — Social Security", expanded=(i == 0)):
        # Defaults for first two people (claim age + PIA)
        if i == 0:
            _def_claim_y = 66
            _def_claim_m = 10
            _def_pia = 3500.0
        elif i == 1:
            _def_claim_y = 66
            _def_claim_m = 4
            _def_pia = 1000.0
        else:
            _def_claim_y = 67
            _def_claim_m = 0
            _def_pia = 3000.0

        claim_year_options = list(range(62, 71))
        claim_month_options = list(range(0, 12))
        _year_index = claim_year_options.index(int(_def_claim_y)) if int(_def_claim_y) in claim_year_options else claim_year_options.index(67)
        _month_index = claim_month_options.index(int(_def_claim_m)) if int(_def_claim_m) in claim_month_options else 0

        col_y, col_m = st.columns(2)
        with col_y:
            claim_age_y = st.selectbox(
                f"Claim age (years) {i+1}",
                options=claim_year_options,
                index=_year_index,
                key=f"claimy_{i}"
            )
        with col_m:
            claim_age_m = st.selectbox(
                f"Claim age (months) {i+1}",
                options=claim_month_options,
                index=_month_index,
                key=f"claimm_{i}"
            )

        pia = st.number_input(
            f"PIA @ FRA (monthly) {i+1}",
            min_value=0.0, value=float(_def_pia), step=50.0, key=f"pia_{i}"
        )

        claim_info.append({
            "claim_age_y": int(claim_age_y),
            "claim_age_m": int(claim_age_m),
            "pia": float(pia),
        })

# ── Assemble Person objects from the two sections ─────────────────────
people = []
for i in range(int(n_people)):
    b = basic_info[i]
    c = claim_info[i] if i < len(claim_info) else {"claim_age_y": 67, "claim_age_m": 0, "pia": 0.0}
    if not b["name"]:
        continue
    if b["dob"] is None or b.get("dob_error"):
        # Skip assembling this person due to DOB parse issues
        continue
    people.append(
        Person(
            name=b["name"],
            dob=b["dob"],
            life_age=b["life_age"],
            claim_age_years=c["claim_age_y"],
            claim_age_months=c["claim_age_m"],
            pia_at_fra=c["pia"],
        )
    )

#
# ═══════════════════════════════════════════════════════════════════════
# SECTION: Summary Output Table (Ages & EOL)
# ═══════════════════════════════════════════════════════════════════════
if people and st.session_state.get("do_calc"):
    rows = []
    today = date.today()

    for p in people:
        age_now = compute_age(p.dob, today)
        years_left = max(p.life_age - age_now, 0)
        rows.append({
            "Name": p.name,
            "DOB": p.dob.strftime("%d/%m/%Y"),
            "Current Age": age_now,
            "Life Expectancy": p.life_age,
            "Years Remaining": years_left,
            "End-of-Life Date": p.eol_date.strftime("%Y-%m-%d"),
            "Claim Age (y:m)": f"{p.claim_age_years}:{p.claim_age_months:02d}",
            "FRA (y:m)": f"{p.fra[0]}:{p.fra[1]:02d}",
            "PIA @ FRA (monthly)": round(p.pia_at_fra, 2),
        })

        if p.life_age < age_now:
            st.sidebar.warning(f"⚠️ {p.name}: life expectancy ({p.life_age}) is below current age ({age_now}).")

    df = pd.DataFrame(rows)

    # Format numeric columns to display as whole numbers (no decimals)
    for col in ["Current Age", "Life Expectancy", "Years Remaining"]:
        if col in df.columns:
            df[col] = df[col].round(0).astype(int)
    if "PIA @ FRA (monthly)" in df.columns:
        df["PIA @ FRA (monthly)"] = df["PIA @ FRA (monthly)"].round(0).astype(int)

    st.subheader("Summary")
    st.dataframe(df, hide_index=True, use_container_width=True)

    # ───────────────────────────────────────────────────────────────────
    # SUBSECTION: Ages by Future Year (Projection Grid)
    # ───────────────────────────────────────────────────────────────────
    if not df.empty:
        max_years = int(df["Years Remaining"].max())
        if max_years > 0:
            future_years = list(range(1, max_years + 1))

            # Build a column per person with ages each future year; blank after life age
            ages_by_year: dict[str, list[int | None]] = {}
            for _, r in df.iterrows():
                name = r["Name"]
                age_now = int(r["Current Age"])
                life_age = int(r["Life Expectancy"])
                series: list[int | None] = []
                for y in future_years:
                    age_at = age_now + y
                    series.append(age_at if age_at <= life_age else None)
                ages_by_year[name] = series

            future_df = pd.DataFrame({"Year": future_years})
            for name, series in ages_by_year.items():
                future_df[name] = series

            # Transpose so years become columns and people become rows
            future_df = future_df.set_index("Year").T.reset_index().rename(columns={"index": "Name"})

            # Format ages in future_df to be whole numbers (no decimals)
            for col in future_df.columns:
                if col == "Name":
                    continue
                future_df[col] = future_df[col].apply(lambda x: int(x) if pd.notnull(x) else None)

            st.subheader("Ages by Future Year")
            st.dataframe(future_df, hide_index=True, use_container_width=True)
        else:
            st.info("No future years to display — all entries have zero years remaining.")

    #
    # ═══════════════════════════════════════════════════════════════════
    # SECTION: Social Security Projection (Annual, No COLA)
    # ═══════════════════════════════════════════════════════════════════
    st.subheader("Social Security — Annual Projection (no COLA)")

    max_years = int(df["Years Remaining"].max())
    if max_years > 0:
        ss_df = project_social_security(people, start=date.today(), years=max_years)
        # Format numeric columns in ss_df to display as whole numbers
        for col in ss_df.columns:
            if pd.api.types.is_numeric_dtype(ss_df[col]):
                ss_df[col] = ss_df[col].round(0).astype(int)
        # Always show years as rows
        st.dataframe(ss_df, hide_index=True, use_container_width=True)
    else:
        st.info("No Social Security rows to display (check claim ages and life expectancy).")

    #
    # ═══════════════════════════════════════════════════════════════════
    # FOOTNOTE: Modeling Assumptions & Notes
    # ═══════════════════════════════════════════════════════════════════
    st.caption(
        "Notes: Current age is calculated from today’s date and the DOB. "
        "End-of-life date reflects the interpretation that a person lives THROUGH the entered age "
        "(death occurs just before the next birthday). "
        "Social Security calculations use simplified but realistic monthly rules: no benefit is payable "
        "for the month of death; spousal benefits stop at death; survivor benefits begin the month after "
        "death if the survivor is age-eligible; early-claim reductions and delayed credits apply, with "
        "delayed credits capped at age 70."
    )
else:
    if not people:
        st.info("Use the sidebar to add at least one person, then click **Calculate**.")
    elif not st.session_state.get("do_calc"):
        st.info("Inputs are ready. Click **Calculate** in the sidebar to run the projections.")