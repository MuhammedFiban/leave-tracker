from datetime import date
from dateutil.relativedelta import relativedelta

def count_calendar_days(start: date, end: date) -> int:
    """Return total days between start and end inclusive (calendar days)."""
    return (end - start).days + 1

def months_between(start: date, end: date) -> float:
    """
    Calculate the exact number of months between two dates (prorated).
    For leave accrual, each full month gives 2.5 days; partial months are prorated.
    """
    if start > end:
        return 0.0

    months = (end.year - start.year) * 12 + (end.month - start.month)

    # Adjust for the day of the month
    if end.day < start.day:
        months -= 1
        # Fraction of the previous month
        prev_month_end = end - relativedelta(months=1)
        days_in_prev = (prev_month_end + relativedelta(months=1) - prev_month_end).days
        fraction = min(1.0, end.day / days_in_prev) if days_in_prev > 0 else 0
        months += fraction
    else:
        if end.day != start.day:
            days_in_month = (date(end.year, end.month, 1) + relativedelta(months=1) - date(end.year, end.month, 1)).days
            fraction = (end.day - start.day) / days_in_month
            months += fraction
    return max(0.0, months)

def accrued_days_up_to(join_date: date, target_date: date) -> float:
    """
    Cumulative leave accrual from join_date to target_date (inclusive).
    Each month (including partial) yields 2.5 days.
    """
    months = months_between(join_date, target_date)
    return months * 2.5