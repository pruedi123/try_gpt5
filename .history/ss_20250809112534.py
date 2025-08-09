from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from math import floor
import pandas as pd

# ---------- Core helpers ----------
def compute_age(dob: date, today: date | None = None) -> int:
    if today is None:
        today = date.today()
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return max(years, 0)

def safe_eol_date(dob: date, life_age: int) -> date:
    year = dob.year + life_age
    try:
        return date(year, dob.month, dob.day)
    except ValueError:
        from calendar import monthrange
        last_day = monthrange(year, dob.month)[1]
        return date(year, dob.month, last_day)

def fra_for_birth_year(y: int) -> tuple[int, int]:
    if y <= 1937: return 65, 0
    if 1938 <= y <= 1942: return 65, (y - 1937) * 2
    if 1943 <= y <= 1954: return 66, 0
    if 1955 <= y <= 1959: return 66, (y - 1954) * 2
    if y >= 1960: return 67, 0
    return 67, 0

def months_between(yrs_a: int, mos_a: int, yrs_b: int, mos_b: int) -> int:
    return (yrs_a * 12 + mos_a) - (yrs_b * 12 + mos_b)

def retirement_adjustment(pia: float, months_from_fra: int) -> float:
    if months_from_fra == 0:
        return pia
    if months_from_fra < 0:
        m = -months_from_fra
        first = min(m, 36)
        extra = max(m - 36, 0)
        reduction = first * (5/900) + extra * (5/1200)
        return pia * max(0.0, 1.0 - reduction)
    return pia * (1.0 + (2/300) * min(months_from_fra, 12 * 4))  # 2/3% up to age 70

def spousal_base(pia_worker: float) -> float: return 0.5 * pia_worker
def spousal_reduction(months_early: int) -> float:
    if months_early <= 0: return 1.0
    first = min(months_early, 36); extra = max(months_early - 36, 0)
    return max(0.0, 1.0 - (first * (25/3600) + extra * (5/1200)))

def survivor_reduction(months_early: int) -> float:
    if months_early <= 0: return 1.0
    return max(0.715, 1.0 - months_early * 0.00396)  # simplified

def add_years_months(d: date, y: int, m: int) -> date:
    y_total = d.year + y + (d.month - 1 + m) // 12
    m_total = (d.month - 1 + m) % 12 + 1
    from calendar import monthrange
    day = min(d.day, monthrange(y_total, m_total)[1])
    return date(y_total, m_total, day)

def first_of_month(d: date) -> date: return date(d.year, d.month, 1)
def add_months(d: date, m: int) -> date:
    y_total = d.year + (d.month - 1 + m) // 12
    m_total = (d.month - 1 + m) % 12 + 1
    from calendar import monthrange
    day = min(d.day, monthrange(y_total, m_total)[1])
    return date(y_total, m_total, day)

def age_ym(dob: date, asof: date) -> tuple[int, int]:
    y = asof.year - dob.year
    m = asof.month - dob.month
    if asof.day < dob.day: m -= 1
    if m < 0: y -= 1; m += 12
    return max(y, 0), max(m, 0)

def months_between_firsts(a: date, b: date) -> int:
    return months_between(a.year, a.month, b.year, b.month)

def clamp_months_in_year(start_month: date, end_month_excl: date, win_start: date, win_end_excl: date) -> int:
    s = first_of_month(max(start_month, win_start))
    e = first_of_month(min(end_month_excl, win_end_excl))
    return max(0, months_between_firsts(e, s))

# ---------- Data model ----------
@dataclass
class Person:
    name: str
    dob: date
    life_age: int
    claim_age_years: int = 67
    claim_age_months: int = 0
    pia_at_fra: float = 0.0

    @property
    def fra(self) -> tuple[int, int]: return fra_for_birth_year(self.dob.year)
    @property
    def claim_date(self) -> date: return add_years_months(self.dob, self.claim_age_years, self.claim_age_months)
    @property
    def eol_date(self) -> date: return safe_eol_date(self.dob, self.life_age + 1)  # lives THROUGH life_age

# ---------- Benefit math ----------
def worker_monthly_at_claim(p: Person) -> float:
    fra_y, fra_m = p.fra
    months_from_fra = months_between(p.claim_age_years, p.claim_age_months, fra_y, fra_m)
    return retirement_adjustment(p.pia_at_fra, months_from_fra)

def survivor_annual(survivor: Person, decedent: Person, death_date: date) -> float:
    # survivor eligibility
    surv_age_y, surv_age_m = age_ym(survivor.dob, death_date)
    if (surv_age_y * 12 + surv_age_m) < 60 * 12: return 0.0

    # decedent benefit at death
    claimed_by_death = death_date >= decedent.claim_date
    if claimed_by_death:
        fra_y, fra_m = decedent.fra
        months_from_fra_at_claim = months_between(decedent.claim_age_years, decedent.claim_age_months, fra_y, fra_m)
        dec_mo = retirement_adjustment(decedent.pia_at_fra, months_from_fra_at_claim)
    else:
        fra_y, fra_m = decedent.fra
        age_y, age_m = age_ym(decedent.dob, death_date)
        mf = months_between(age_y, age_m, fra_y, fra_m)
        if mf >= 0:
            cap_months = min(mf, (70 - fra_y) * 12)
            dec_mo = retirement_adjustment(decedent.pia_at_fra, cap_months)
        else:
            dec_mo = decedent.pia_at_fra

    # survivor reduction
    fra_y_s, fra_m_s = survivor.fra
    months_early = max(0, months_between(fra_y_s, fra_m_s, surv_age_y, surv_age_m))
    factor = survivor_reduction(months_early)
    surv_mo = min(dec_mo, dec_mo * factor)  # cap at decedent’s at-death benefit
    return 12.0 * surv_mo

# ---------- Projection ----------
def project_social_security(people: list[Person], start: date, years: int) -> pd.DataFrame:
    if years <= 0: return pd.DataFrame()

    eol_map = {p.name: p.eol_date for p in people}
    claim_map = {p.name: p.claim_date for p in people}
    mo_at_claim = {p.name: worker_monthly_at_claim(p) for p in people}

    rows = []
    for y in range(1, years + 1):
        asof = add_years_months(start, y, 0)
        year_start = first_of_month(asof)
        year_end_excl = first_of_month(add_years_months(asof, 1, 0))

        # own (cap at spouse death month for couples)
        own = {p.name: 0.0 for p in people}
        own_months = {}
        for idx, p in enumerate(people):
            claim_first = first_of_month(claim_map[p.name])
            own_death_first = first_of_month(eol_map[p.name])
            if len(people) == 2:
                other = people[1 - idx]
                spouse_death_first = first_of_month(eol_map[other.name])
                own_window_end = min(own_death_first, spouse_death_first)
            else:
                own_window_end = own_death_first
            months_paid = clamp_months_in_year(claim_first, own_window_end, year_start, year_end_excl)
            own_months[p.name] = months_paid
            own[p.name] = mo_at_claim[p.name] * months_paid

        # spousal (both alive & both filed)
        spousal = {p.name: 0.0 for p in people}
        if len(people) == 2:
            a, b = people[0], people[1]
            both_alive_end = min(first_of_month(eol_map[a.name]), first_of_month(eol_map[b.name]), year_end_excl)
            if claim_map[a.name] <= add_years_months(asof, 1, 0) and claim_map[b.name] <= add_years_months(asof, 1, 0):
                base = max(0.0, spousal_base(b.pia_at_fra) - a.pia_at_fra)
                fra_y, fra_m = a.fra
                months_early = max(0, -months_between(a.claim_age_years, a.claim_age_months, fra_y, fra_m))
                sp_mo = base * spousal_reduction(months_early)
                spousal[a.name] = sp_mo * clamp_months_in_year(first_of_month(max(claim_map[a.name], claim_map[b.name])), both_alive_end, year_start, year_end_excl)
            if claim_map[b.name] <= add_years_months(asof, 1, 0) and claim_map[a.name] <= add_years_months(asof, 1, 0):
                base = max(0.0, spousal_base(a.pia_at_fra) - b.pia_at_fra)
                fra_y, fra_m = b.fra
                months_early = max(0, -months_between(b.claim_age_years, b.claim_age_months, fra_y, fra_m))
                sp_mo = base * spousal_reduction(months_early)
                spousal[b.name] = sp_mo * clamp_months_in_year(first_of_month(max(claim_map[a.name], claim_map[b.name])), both_alive_end, year_start, year_end_excl)

        total = {p.name: own[p.name] + spousal[p.name] for p in people}

        # survivor higher-of
        if len(people) == 2:
            a, b = people[0], people[1]
            a_death = first_of_month(eol_map[a.name]); b_death = first_of_month(eol_map[b.name])

            def add_surv(surv: Person, dec: Person, dec_death_first: date):
                # full-year after death
                if dec_death_first <= year_start:
                    months_surv = months_between_firsts(year_end_excl, year_start)
                    if months_surv > 0:
                        surv_mo = survivor_annual(surv, dec, dec_death_first) / 12.0
                        own_mo = mo_at_claim[surv.name]
                        total[surv.name] += max(surv_mo, own_mo) * months_surv
                    return
                # death during this year → month after death to year end
                if year_start < dec_death_first <= year_end_excl:
                    surv_start = add_months(dec_death_first, 1)
                    months_surv = max(0, months_between_firsts(year_end_excl, surv_start))
                    if months_surv > 0:
                        surv_mo = survivor_annual(surv, dec, dec_death_first) / 12.0
                        own_mo = mo_at_claim[surv.name]
                        total[surv.name] += max(surv_mo, own_mo) * months_surv

            add_surv(a, b, b_death); add_surv(b, a, a_death)

        row = {"Year": y}
        for p in people:
            row[f"{p.name} Own"] = round(own[p.name], 2) or None
            row[f"{p.name} Spousal"] = round(spousal[p.name], 2) or None
            row[f"{p.name} Total SS"] = round(total[p.name], 2) or None
            # debug
            row[f"{p.name} Monthly@Claim"] = round(mo_at_claim[p.name], 2)
            row[f"{p.name} MonthsPaidOwn"] = int(own_months.get(p.name, 0))
            row[f"{p.name} OwnCalc"] = round(mo_at_claim[p.name]*own_months.get(p.name,0), 2)
        row["Household Total SS"] = round(sum(total.values()), 2)
        rows.append(row)

    return pd.DataFrame(rows)