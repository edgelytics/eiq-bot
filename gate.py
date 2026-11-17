"""gate.py — cheap check the scheduler runs first: prints the upcoming slot name, or nothing."""
import datetime as dt
from zoneinfo import ZoneInfo
import config

now = dt.datetime.now(ZoneInfo(config.TIMEZONE))
for sl in config.SLOTS:
    hh, mm = map(int, sl["post"].split(":"))
    mins = (now.replace(hour=hh, minute=mm, second=0, microsecond=0) - now).total_seconds() / 60
    if -10 <= mins <= 50:
        print(sl["name"])
        break
