# Egyptian conventions: "." as decimal separator (Django's generic Arabic
# locale uses "," which breaks number inputs), Saturday as first day of week.
DATE_FORMAT = "d/m/Y"
TIME_FORMAT = "g:i A"
DATETIME_FORMAT = "d/m/Y g:i A"
YEAR_MONTH_FORMAT = "F Y"
MONTH_DAY_FORMAT = "j F"
SHORT_DATE_FORMAT = "d/m/Y"
SHORT_DATETIME_FORMAT = "d/m/Y g:i A"
FIRST_DAY_OF_WEEK = 6
DATE_INPUT_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]
TIME_INPUT_FORMATS = ["%H:%M", "%H:%M:%S", "%I:%M %p"]
DATETIME_INPUT_FORMATS = ["%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]
DECIMAL_SEPARATOR = "."
THOUSAND_SEPARATOR = ","
NUMBER_GROUPING = 3
