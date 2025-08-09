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

@dataclass
class Person:
    name: str
    dob: date
    life_age: int

    @property
    def age(self) -> int:
        return compute_age(self.dob)

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
            f"Life expectancy age (they will live through) {i+1}",
            min_value=50, max_value=120, value=95, step=1, key=f"life_{i}"
        )
        if name.strip():
            people.append(Person(name=name.strip(), dob=dob, life_age=int(life_age)))

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
            "Life Expectancy Age (through)": p.life_age,
            "Years Remaining": years_left,
            "End-of-Life Date": eol.strftime("%Y-%m-%d"),
        })

        if p.life_age < age_now:
            st.sidebar.warning(f"⚠️ {p.name}: life expectancy age ({p.life_age}) is below current age ({age_now}).")

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
                life_age = int(r["Life Expectancy Age (through)"])
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

    st.caption(
        "Notes: Current age is calculated from today’s date and the DOB. "
        "End-of-life date is December 31 of the year the person reaches the life expectancy age."
    )
else:
    st.info("Use the sidebar to add at least one person.")