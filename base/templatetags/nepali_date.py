"""
Template filters for displaying Nepali (Bikram Sambat / BS) dates.

This module is purely additive: it does not change how dates are stored,
validated, or calculated anywhere in the app. It only converts an existing
AD (Gregorian) date to a BS string for DISPLAY in a template. Every model
field, form, filter, and date calculation elsewhere in the app is completely
untouched and keeps working exactly as it does today.

Usage in any template:
    {% load nepali_date %}
    {{ employee.dob|to_bs }}                  -> "14 Bhadra 2083"
    {{ leave_request.start_date|to_bs:"num" }} -> "2083-05-14"
"""

import datetime

import nepali_datetime
from django import template

register = template.Library()

# nepali_datetime's own strftime("%B") ships with a typo ("Bhadau" instead of
# "Bhadra") baked into its _FULLMONTHNAMES constant -- even the library's own
# calendar_bs.csv data file spells it "Bhadra". Rather than depend on that,
# we keep the correct spellings here and build the month name ourselves.
BS_MONTH_NAMES = (
    None,
    "Baishakh",
    "Jestha",
    "Asar",
    "Shrawan",
    "Bhadra",
    "Aswin",
    "Kartik",
    "Mangsir",
    "Poush",
    "Magh",
    "Falgun",
    "Chaitra",
)


@register.filter(name="to_bs")
def to_bs(value, fmt="text"):
    """Convert an AD date/datetime to a BS date string.

    Returns an empty string for None or values that aren't actually a date,
    rather than raising -- a date field being blank or a value coming in as
    the wrong type should never break page rendering.

    fmt="text" (default) -> "14 Bhadra 2083"
    fmt="num"             -> "2083-05-14"
    """
    if value is None:
        return ""

    # Accept both date and datetime (datetime is a subclass of date, but
    # from_datetime_date wants a plain date, so normalize here).
    if isinstance(value, datetime.datetime):
        value = value.date()
    if not isinstance(value, datetime.date):
        return ""

    try:
        bs_date = nepali_datetime.date.from_datetime_date(value)
    except Exception:
        # Conversion library has a defined valid range; anything outside it
        # (or any unexpected error) degrades to blank rather than a 500.
        return ""

    if fmt == "num":
        return bs_date.strftime("%Y-%m-%d")
    return f"{bs_date.day:02d} {BS_MONTH_NAMES[bs_date.month]} {bs_date.year}"
