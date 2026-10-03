"""Registering a school's students or teachers in bulk (Control room >
Bulk add students / Bulk add teachers). Both work the same way; KINDS holds
what differs.

1. The admin downloads an Excel template for a school.
2. They fill in a row per person (first name, last name, level, and an
   email if they have one) and upload it.
3. Every row is checked first; if any row has a problem nothing is created
   and the problems are listed by row. Otherwise each gets an account in
   that school, at that level, covered by the school's plan. Students are
   capped by "Students allowed", teachers by the school's teacher limit.
4. The logins (username + a new password) come back as an Excel sheet to
   send to the school. Django stores its normal one-way password hash; a
   separate encrypted copy makes future school login downloads possible.

Everyone signs in with a username made from their name (ada.okafor,
then ada.okafor2 ...) and a very simple password (mango47). An email is
optional; one given in the sheet is kept on the account.
"""

import base64
import io
import re
import secrets

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import User
from apps.echospell.models import LEVEL_NAME_CHOICES

LEVELS = [value for value, _label in LEVEL_NAME_CHOICES]
MAX_ROWS = 1000
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

KINDS = {
    "student": {
        "role": User.Role.STUDENT, "one": "student", "many": "students", "One": "Student", "Many": "Students",
        "level_head": "Level *", "level_help": "Each student sees only their level.",
        "email_help": "The student's or a parent's email. Leave it blank and they sign in with their username.",
        "examples": [("1", "Ada", "Okafor · Level 1 · (no email)"), ("2", "Tunde", "Bello · Level 2 · tunde.parent@example.com")],
    },
    "teacher": {
        "role": User.Role.TEACHER, "one": "teacher", "many": "teachers", "One": "Teacher", "Many": "Teachers",
        "level_head": "Level taught *", "level_help": "The level they teach: they see that level's lessons and its students' work.",
        "email_help": "The teacher's email. Leave it blank and they sign in with their username.",
        "examples": [("1", "Grace", "Adeyemi · Level 3 · grace.adeyemi@example.com"), ("2", "Musa", "Ibrahim · Level 5 · (no email)")],
    },
}


def room_for(school, kind):
    """(allowed, already there) for this school, allowed None = no cap."""
    if kind == "teacher":
        return school.teacher_limit, school.teachers.count()
    return school.max_students, school.students.count()


WORDS = (
    "mango river sun lemon apple tiger lion zebra panda robin star moon cake "
    "honey pearl ruby bird fish kite ship tree rose lily book bell drum"
).split()


def new_password():
    """Very simple to type (young learners especially): a short word and two
    numbers, all lower case, e.g. mango47."""
    return f"{secrets.choice(WORDS)}{secrets.randbelow(90) + 10}"


# ---------------------------------------------------------------- styling

NAVY, BLUE, YELLOW, SKY, WASH, LINE, MUTED = "0B1A4A", "1846E0", "FFC72C", "E7EFFF", "F2F5FC", "D6E3FF", "55607E"
FIRST_DATA_ROW = 6          # rows 1-4 are the school's banner, row 5 the headings


def _banner(ws, school, subtitle, last_col):
    """Rows 1-4: the Diction Masters bar, the school's name, its code and a line of help."""
    from openpyxl.styles import Alignment, Font, PatternFill

    span = f"A{{r}}:{last_col}{{r}}"
    for r in (1, 2, 3):
        ws.merge_cells(span.format(r=r))
    ws["A1"] = "DICTION MASTERS"
    ws["A1"].font = Font(name="Calibri", bold=True, size=11, color=YELLOW)
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 24
    school_title = str(school.name or "")
    if school_title.startswith(("=", "+", "-", "@", "\t", "\r")):
        school_title = "'" + school_title
    ws["A2"] = school_title
    ws["A2"].font = Font(name="Calibri", bold=True, size=20, color="FFFFFF")
    ws["A2"].fill = PatternFill("solid", fgColor=BLUE)
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 40
    ws["A3"] = subtitle
    ws["A3"].font = Font(name="Calibri", size=11, color=NAVY)
    ws["A3"].fill = PatternFill("solid", fgColor=SKY)
    ws["A3"].alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
    ws.row_dimensions[3].height = 34
    ws.row_dimensions[4].height = 8
    ws.sheet_properties.tabColor = BLUE


def _heading_row(ws, row, headings, widths):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    edge = Side(style="thin", color=NAVY)
    for i, (text, width) in enumerate(zip(headings, widths), start=1):
        cell = ws.cell(row=row, column=i, value=text)
        cell.font = Font(name="Calibri", bold=True, size=12, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
        cell.border = Border(bottom=Side(style="medium", color=YELLOW), left=edge, right=edge, top=edge)
        ws.column_dimensions[cell.column_letter].width = width
    ws.row_dimensions[row].height = 28


def _body_rows(ws, first, last, cols):
    """Zebra stripes and light borders, so the sheet reads like a register."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    line = Side(style="thin", color=LINE)
    stripe = PatternFill("solid", fgColor=WASH)
    for r in range(first, last + 1):
        ws.row_dimensions[r].height = 22
        for c in range(1, cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = Border(left=line, right=line, top=line, bottom=line)
            cell.alignment = Alignment(vertical="center", indent=1)
            cell.font = Font(name="Calibri", size=11, color=NAVY)
            if (r - first) % 2:
                cell.fill = stripe


def _print_setup(ws, school, title, header_row):
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{header_row}:{header_row}"
    ws.oddHeader.center.text = f"{school.name} — {title}"
    ws.oddFooter.center.text = "Diction Masters · Page &P of &N"
    ws.sheet_view.showGridLines = False


# ---------------------------------------------------------------- template

def template_file(school, kind="student"):
    """The Excel sheet to fill in: the school's banner, a Level dropdown,
    and ready-lined rows."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    k = KINDS[kind]
    wb = Workbook()
    ws = wb.active
    ws.title = k["Many"]
    head = FIRST_DATA_ROW - 1
    last = head + MAX_ROWS
    _banner(ws, school,
            f"School code {school.code}  ·  {k['One']} register  ·  One row per {k['one']}. "
            "First name and Level are required; Email is optional.", "E")
    _heading_row(ws, head, ["#", "First name *", "Last name", k["level_head"], "Email (optional)"], (6, 24, 24, 18, 38))
    _body_rows(ws, FIRST_DATA_ROW, FIRST_DATA_ROW + 199, 5)
    for i, r in enumerate(range(FIRST_DATA_ROW, FIRST_DATA_ROW + 200), start=1):
        cell = ws.cell(row=r, column=1, value=i)
        cell.font = Font(name="Calibri", size=10, color=MUTED)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # A live count of people filled in, top right.
    ws["E4"] = f'=COUNTA(B{FIRST_DATA_ROW}:B{last})&" {k['many']} listed"'
    ws["E4"].font = Font(name="Calibri", bold=True, size=10, color=BLUE)
    ws["E4"].alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[4].height = 18

    levels = wb.create_sheet("Levels")
    for level in LEVELS:
        levels.append([level])
    levels.sheet_state = "hidden"
    pick = DataValidation(type="list", formula1=f"=Levels!$A$1:$A${len(LEVELS)}", allow_blank=True,
                          showErrorMessage=True, errorTitle="Level", error="Choose a level from the list.",
                          showInputMessage=True, promptTitle="Level", prompt=f"Choose {LEVELS[0]} to {LEVELS[-1]}.")
    ws.add_data_validation(pick)
    pick.add(f"D{FIRST_DATA_ROW}:D{last}")
    email_tip = DataValidation(type="custom", formula1="TRUE", allow_blank=True, showInputMessage=True,
                               promptTitle="Email (optional)",
                               prompt=k["email_help"])
    ws.add_data_validation(email_tip)
    email_tip.add(f"E{FIRST_DATA_ROW}:E{last}")
    ws.freeze_panes = f"B{FIRST_DATA_ROW}"
    ws.auto_filter.ref = f"A{head}:E{last}"
    _print_setup(ws, school, f"{k['One']} register", head)

    guide = wb.create_sheet("How to fill this in")
    _banner(guide, school, f"How to fill in the {k['one']} register", "C")
    guide.column_dimensions["A"].width = 6
    guide.column_dimensions["B"].width = 34
    guide.column_dimensions["C"].width = 70
    steps = [
        ("1", f"One row per {k['one']}", f"On the {k['Many']} sheet, fill in one row for each {k['one']}, starting on row 1."),
        ("2", "First name *", "Required."),
        ("3", "Last name", f"Optional, but it helps the school tell {k['many']} apart."),
        ("4", k["level_head"], f"Required. Pick from the dropdown: {LEVELS[0]} to {LEVELS[-1]}. {k['level_help']}"),
        ("5", "Email (optional)", k["email_help"]),
        ("6", "Upload", f"Save the file and upload it in the Diction Masters control room: Bulk add {k['many']}. Up to {MAX_ROWS} at a time."),
        ("7", "Logins", f"Straight after the upload you can download every {k['one']}'s username and password to share."),
    ]
    _heading_row(guide, 5, ["", "Column / step", "What to do"], (6, 34, 70))
    _body_rows(guide, 6, 5 + len(steps), 3)
    for i, (n, what, how) in enumerate(steps, start=6):
        guide.cell(row=i, column=1, value=n).font = Font(bold=True, color=BLUE)
        guide.cell(row=i, column=2, value=what).font = Font(bold=True, color=NAVY)
        cell = guide.cell(row=i, column=3, value=how)
        cell.alignment = Alignment(wrap_text=True, vertical="center", indent=1)
        guide.row_dimensions[i].height = 34
    ex = 6 + len(steps) + 1
    guide.cell(row=ex, column=2, value="Example rows").font = Font(bold=True, color=NAVY)
    _heading_row(guide, ex + 1, ["#", "First name *", "Last name"], (6, 34, 70))
    for j, row in enumerate(k["examples"], start=ex + 2):
        for c, v in enumerate(row, start=1):
            guide.cell(row=j, column=c, value=v).fill = PatternFill("solid", fgColor=WASH)
    guide.sheet_view.showGridLines = False
    guide.sheet_properties.tabColor = YELLOW

    wb.active = 0
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ----------------------------------------------------------------- reading

def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _level(raw):
    wanted = _norm(raw).lower().replace("pre level", "pre-level")
    if wanted.isdigit():
        wanted = f"level {wanted}"
    return next((lv for lv in LEVELS if lv.lower() == wanted), None)


def read_rows(upload, kind="student"):
    """[(row number, {first, last, level, email})] from an .xlsx or .csv.
    The heading row is found wherever it is (the template has a banner
    above it), and columns are matched by their headings."""
    name = (upload.name or "").lower()
    if name.endswith(".csv"):
        import csv

        text = upload.read().decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
    else:
        from openpyxl import load_workbook

        try:
            wb = load_workbook(upload, read_only=True, data_only=True)
        except Exception:
            raise ValueError("That file couldn't be read. Upload the Excel template (.xlsx) or a .csv file.")
        sheet = KINDS[kind]["Many"]
        ws = wb[sheet] if sheet in wb.sheetnames else wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    if not rows:
        raise ValueError("The file is empty.")

    def key(text):
        return re.sub(r"[^a-z]", "", _norm(text).lower())

    head_at, cols = None, {}
    for i, row in enumerate(rows[:20]):
        keys = [key(c) for c in row]
        if any(k.startswith("firstname") for k in keys):
            head_at = i
            for j, k in enumerate(keys):
                if k.startswith("firstname"):
                    cols.setdefault("first", j)
                elif k.startswith("lastname") or k.startswith("surname"):
                    cols.setdefault("last", j)
                elif k.startswith("level") or k.startswith("class"):
                    cols.setdefault("level", j)
                elif k.startswith("email"):
                    cols.setdefault("email", j)
            break
    if head_at is None or "level" not in cols:
        raise ValueError("Couldn't find the headings (First name, Last name, Level, Email). Use the template.")

    def cell(row, field):
        j = cols.get(field)
        return _norm(row[j]) if j is not None and j < len(row) else ""

    out = []
    for n, row in enumerate(rows[head_at + 1:], start=head_at + 2):
        r = {"first": cell(row, "first"), "last": cell(row, "last"), "level_raw": cell(row, "level"),
             "email": cell(row, "email").lower()}
        if not any(r.values()):
            continue
        out.append((n, r))
    if len(out) > MAX_ROWS:
        raise ValueError(f"That's {len(out)} {KINDS[kind]['many']}; upload at most {MAX_ROWS} at a time.")
    return out


# ------------------------------------------------------------------ checks

def check(school, rows, kind="student"):
    """(clean rows, problems). Problems: [(row number, message)]."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    problems, clean, seen = [], [], set()
    for n, r in rows:
        errs = []
        if not r["first"]:
            errs.append("first name is missing")
        level = _level(r["level_raw"])
        if not level:
            errs.append(f"level “{r['level_raw'] or '(blank)'}” isn't one of {LEVELS[0]}–{LEVELS[-1]}")
        if r["email"]:
            try:
                validate_email(r["email"])
            except ValidationError:
                errs.append(f"“{r['email']}” isn't an email address")
            else:
                if r["email"] in seen:
                    errs.append(f"{r['email']} is used twice in the file")
                elif User.objects.filter(email__iexact=r["email"]).exists():
                    errs.append(f"an account already uses {r['email']}")
                seen.add(r["email"])
        if errs:
            problems.append((n, "; ".join(errs)))
        else:
            clean.append({**r, "level": level, "row": n})
    allowed, have = room_for(school, kind)
    if allowed is not None:
        room = allowed - have
        if len(clean) > room and not problems:
            fix = ("Raise “Teachers allowed” on the school or move it to a bigger plan, or upload fewer."
                   if kind == "teacher" else "Raise “Students allowed” on the school, or upload fewer.")
            many = KINDS[kind]["many"]
            problems.append((0, f"{school.name} can register {allowed} {many} and has "
                                f"{have}, so there's room for {max(room, 0)} more, not {len(clean)}. {fix}"))
    return clean, problems


@transaction.atomic
def create(school, clean, kind="student"):
    """Make the accounts. Each one signs in with a username and a
    simple password; an email is kept only if one was given.
    Returns [{first, last, level, username, email, password}]."""
    from apps.accounts.forms import internal_email, unique_username

    made = []
    for r in clean:
        username = unique_username(r["first"], r["last"])
        password = new_password()
        User.objects.create_user(
            email=r["email"] or internal_email(username), username=username, password=password,
            first_name=r["first"], last_name=r["last"], role=KINDS[kind]["role"], school=school, level=r["level"],
        )
        made.append({"first": r["first"], "last": r["last"], "level": r["level"], "username": username,
                     "email": r["email"], "password": password})
    return made


def logins_file(school, made, site_url, kind="student"):
    """The login sheet for the school, as a data: URL the browser can save."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    k = KINDS[kind]
    wb = Workbook()
    ws = wb.active
    ws.title = f"{k['One']} logins"
    head = FIRST_DATA_ROW - 1
    _banner(ws, school,
            f"{k['One']} logins  ·  Sign in at {site_url}/accounts/login/ with the username and password  ·  "
            f"Keep this private: give each {k['one']} only their own row.", "G")
    stamp = timezone.localtime()
    ws["G4"] = f"{len(made)} {k['many']} · {stamp:%d %b %Y}"
    ws["G4"].font = Font(name="Calibri", bold=True, size=10, color=BLUE)
    ws["G4"].alignment = Alignment(horizontal="right", vertical="center")
    _heading_row(ws, head, ["#", "First name", "Last name", "Level taught" if kind == "teacher" else "Level", "Username", "Password", "Email (if given)"],
                 (6, 20, 20, 13, 24, 16, 34))
    for i, m in enumerate(made, start=1):
        ws.append([i, m["first"], m["last"], m["level"], m["username"], m["password"], m["email"] or ""])
    _body_rows(ws, FIRST_DATA_ROW, FIRST_DATA_ROW + len(made) - 1, 7)
    for r in range(FIRST_DATA_ROW, FIRST_DATA_ROW + len(made)):
        ws.cell(row=r, column=1).alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=r, column=1).font = Font(size=10, color=MUTED)
        ws.cell(row=r, column=5).font = Font(name="Consolas", bold=True, size=12, color=NAVY)
        ws.cell(row=r, column=6).font = Font(name="Consolas", bold=True, size=12, color=BLUE)
    ws.freeze_panes = f"B{FIRST_DATA_ROW}"
    _print_setup(ws, school, f"{k['One']} logins", head)
    out = io.BytesIO()
    wb.save(out)
    filename = f"{slugify(school.name) or 'school'}-{k['one']}-logins-{stamp:%Y-%m-%d}.xlsx"
    return f"data:{XLSX};base64,{base64.b64encode(out.getvalue()).decode()}", filename


def school_logins_file(school, accounts, site_url, note=None, title="Current logins"):
    """Build a combined login sheet for active school accounts. `note`
    replaces the line of help under the school's name."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    wb = Workbook()
    ws = wb.active
    ws.title = "School logins"
    head = FIRST_DATA_ROW - 1
    available = sum(1 for account in accounts if account.get("password_available"))
    _banner(
        ws, school,
        f"School code {school.code} · {title} · Sign in at {site_url}/accounts/login/ · " + (note or (
            "Passwords are not changed by this download. "
            "Unavailable entries are from before encrypted password recovery, or need the original recovery key.")),
        "H",
    )
    stamp = timezone.localtime()
    ws["H4"] = f"{len(accounts)} active · {available} passwords available · {stamp:%d %b %Y}"
    ws["H4"].font = Font(name="Calibri", bold=True, size=10, color=BLUE)
    _heading_row(ws, head, ["#", "First name", "Last name", "Role", "Level", "Username / login", "Current password", "Email (if given)"],
                 (6, 20, 20, 18, 16, 26, 54, 36))

    def safe_cell(value):
        text = str(value or "")
        return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text

    for number, account in enumerate(accounts, start=1):
        user = account["user"]
        ws.append([
            number,
            safe_cell(user.first_name),
            safe_cell(user.last_name),
            safe_cell(user.get_role_display()),
            safe_cell(user.level_display),
            safe_cell(user.login_name),
            account["password"],
            safe_cell(user.email if user.has_real_email else ""),
        ])
        # Keep passwords exactly as entered while forcing Excel to treat them
        # as text, including passwords that begin with a formula character.
        password_cell = ws.cell(row=FIRST_DATA_ROW + number - 1, column=7)
        password_cell.value = str(account["password"])
        password_cell.data_type = "s"
        password_cell.alignment = Alignment(vertical="center", wrap_text=True)
    _body_rows(ws, FIRST_DATA_ROW, FIRST_DATA_ROW + len(accounts) - 1, 8)
    for row in range(FIRST_DATA_ROW, FIRST_DATA_ROW + len(accounts)):
        ws.cell(row=row, column=1).alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=row, column=6).font = Font(name="Consolas", bold=True, size=11, color=NAVY)
        ws.cell(row=row, column=7).font = Font(name="Consolas", bold=True, size=11, color=BLUE)
    ws.freeze_panes = f"B{FIRST_DATA_ROW}"
    ws.auto_filter.ref = f"A{head}:H{FIRST_DATA_ROW + len(accounts) - 1}"
    _print_setup(ws, school, "School logins", head)
    out = io.BytesIO()
    wb.save(out)
    filename = f"{slugify(school.name) or 'school'}-logins-{stamp:%Y-%m-%d}.xlsx"
    return out.getvalue(), filename
