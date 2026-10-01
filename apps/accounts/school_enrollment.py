"""Create a new school and its first admin, teachers, and students."""

import re
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.db.models.functions import Lower
from django.utils.text import slugify

from apps.accounts.models import INTERNAL_EMAIL_DOMAIN, User

MAX_TEAM_MEMBERS = 250


class SchoolEnrollmentConflict(Exception):
    """A school or login was created by another request during enrollment."""


def _username(first_name, last_name, reserved, fallback):
    parts = [slugify(part) for part in (first_name, last_name) if part]
    base = ".".join(part for part in parts if part).replace("-", "")
    base = re.sub(r"[^a-z0-9.]", "", base).strip(".") or fallback
    if len(base) < 3:
        base = f"{fallback}.{base}" if base else fallback
    base = base[:34].rstrip(".") or fallback
    suffix = 1
    while True:
        suffix_text = "" if suffix == 1 else str(suffix)
        candidate = f"{base[:40 - len(suffix_text)]}{suffix_text}"
        if candidate.casefold() not in reserved:
            reserved.add(candidate.casefold())
            return candidate
        suffix += 1


def _hashed_passwords(passwords):
    if not passwords:
        return []
    with ThreadPoolExecutor(max_workers=min(4, len(passwords))) as pool:
        return list(pool.map(make_password, passwords))


def create_school_team(school_data, admin_data, teachers, students, site_url, plan=None):
    """Create the complete roster and build its login workbook atomically.

    Passwords use the same short, easy-to-type format as the bulk roster
    feature. Django stores its normal password hash; an encrypted copy allows
    future school login downloads without changing anyone's password.
    """
    from apps.accounts.credentials import encrypt_login_password
    from apps.manage.bulk_students import new_password, school_logins_file
    from apps.schools.models import School
    from apps.billing.models import Subscription

    existing_usernames = {
        value.casefold()
        for value in User.objects.exclude(username__isnull=True).values_list("username", flat=True)
        if value
    }
    reserved_internal_emails = {
        value.casefold()
        for value in User.objects.filter(email__iendswith=f"@{INTERNAL_EMAIL_DOMAIN}")
        .values_list("email", flat=True)
    }

    roster = [{**admin_data, "role": User.Role.SCHOOL_ADMIN, "level": ""}]
    roster.extend({**row, "role": User.Role.TEACHER} for row in teachers)
    roster.extend({**row, "role": User.Role.STUDENT} for row in students)

    supplied_emails = [row.get("email", "").strip().lower() for row in roster if row.get("email")]
    if len(supplied_emails) != len(set(supplied_emails)):
        raise SchoolEnrollmentConflict("Each login email must be unique across the school roster.")
    occupied_emails = {
        value.casefold()
        for value in User.objects.annotate(normalized_email=Lower("email"))
        .filter(normalized_email__in=supplied_emails).values_list("email", flat=True)
    }
    if occupied_emails:
        raise SchoolEnrollmentConflict("One or more roster email addresses already belong to an account.")

    from apps.accounts.forms import internal_email

    for row in roster:
        username = _username(
            row["first_name"], row.get("last_name", ""), existing_usernames,
            "admin" if row["role"] == User.Role.SCHOOL_ADMIN else "learner",
        )
        row["username"] = username
        row["email"] = row.get("email", "").strip().lower() or internal_email(username)
        if row["email"].casefold() in reserved_internal_emails:
            # A username is unique, but keep this check explicit for legacy
            # accounts whose usernames and internal emails do not correspond.
            row["username"] = _username(
                row["first_name"], row.get("last_name", ""), existing_usernames, "learner",
            )
            row["email"] = internal_email(row["username"])
        reserved_internal_emails.add(row["email"].casefold())
        row["password"] = new_password()

    hashes = _hashed_passwords([row["password"] for row in roster])
    encrypted_passwords = [encrypt_login_password(row["password"]) for row in roster]
    if not all(encrypted_passwords):
        raise SchoolEnrollmentConflict(
            "Secure password recovery is not configured on this server. Please contact Diction Masters before registering."
        )
    school = School(
        name=school_data["school_name"],
        email=school_data.get("school_email", "") or admin_data.get("email", ""),
        phone=school_data.get("school_phone", ""),
        address=school_data.get("school_address", ""),
        contact_person=f'{admin_data["first_name"]} {admin_data.get("last_name", "")}'.strip(),
    )

    try:
        with transaction.atomic():
            school.save()
            if plan is not None:
                Subscription.objects.create(school=school, plan=plan)
            teacher_limit = school.teacher_limit
            if teacher_limit is not None and len(teachers) > teacher_limit:
                raise SchoolEnrollmentConflict(
                    f"This school plan allows {teacher_limit} teachers; the roster has {len(teachers)}."
                )
            users = []
            for row, password_hash, encrypted_password in zip(roster, hashes, encrypted_passwords):
                users.append(User(
                    email=row["email"],
                    username=row["username"],
                    password=password_hash,
                    first_name=row["first_name"],
                    last_name=row.get("last_name", ""),
                    role=row["role"],
                    school=school,
                    level=row.get("level", ""),
                    encrypted_login_password=encrypted_password,
                ))
            created = User.objects.bulk_create(users, batch_size=100)
            accounts = [
                {"user": user, "password": row["password"], "password_available": True}
                for user, row in zip(created, roster)
            ]
            workbook, filename = school_logins_file(school, accounts, site_url)
    except IntegrityError as error:
        raise SchoolEnrollmentConflict(
            "A school or login with these details was registered at the same time. Please review and submit again."
        ) from error

    return workbook, filename
