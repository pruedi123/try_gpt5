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
    """Return the last day of the year in which the person turns `life_age`.
    The calculation is based on dob.year + life_age, always returning December 31 of that year."""
    year = dob.year + life_age
    return date(year, 12, 31)

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

    st.caption(
        "Notes: Current age is calculated from today’s date and the DOB. "
        "End-of-life date is the birthday on which the person turns the life expectancy age."
    )
else:
    st.info("Use the sidebar to add at least one person.")