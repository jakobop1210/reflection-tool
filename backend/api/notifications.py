from typing import List

from backend.api.main import is_admin

from . import crud
from . import model

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.config import Config
from starlette.responses import JSONResponse

from fastapi_mail import FastMail, MessageSchema, ConnectionConfig

config = Config(".env")


def create_invitation(request, ref, db):
    user = request.session.get("user")
    uid: str = user.get("uid")
    user = crud.get_user(db, uid)
    if user is None:
        raise HTTPException(401, detail="Cannot find your user")
    enrollment = crud.get_enrollment(db, ref.course_id, ref.course_semester, uid)
    if enrollment is None:
        raise HTTPException(401, detail="You are not enrolled in the course")
    if not is_admin(db, request) or not enrollment.role in [
        "lecturer",
        "teaching assistant",
    ]:
        raise HTTPException(403, detail="You are not allowed to invite to this course")
    try:
        return crud.create_invitation(db, invitation=ref.dict())
    except IntegrityError:
        raise HTTPException(409, detail="invitation already exists")


def get_invitations(request, db):
    """
    Retrieves all invitations for a user based on the user ID stored in the session.
    """
    user = request.session.get("user")
    uid: str = user.get("uid")

    return crud.get_invitations(db, uid)


NOTIFICATION_COOLDOWN_DAYS = config("NOTIFICATION_COOLDOWN_DAYS", cast=int, default=1)
NOTIFICATION_LIMIT = config("NOTIFICATION_LIMIT", cast=int, default=2)

email_config = ConnectionConfig(
    MAIL_USERNAME=config("MAIL_USERNAME", cast=str, default=""),
    MAIL_PASSWORD=config("MAIL_PASSWORD", cast=str, default=""),
    MAIL_FROM=config("MAIL_FROM", cast=str, default="test@test.no"),
    MAIL_PORT=config("MAIL_PORT", cast=int, default=587),
    MAIL_SERVER=config("MAIL_SERVER", cast=str, default=""),
    MAIL_FROM_NAME="Reflection Tool",
    MAIL_STARTTLS=False,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=False,
    VALIDATE_CERTS=False,
)


async def send_notifications(db):
    if crud.check_recent_notification(db, NOTIFICATION_COOLDOWN_DAYS):
        print(
            "Notification already sent in the last", NOTIFICATION_COOLDOWN_DAYS, "days"
        )
        raise HTTPException(
            status_code=400,
            detail="A notification has already been sent in the last "
            + str(NOTIFICATION_COOLDOWN_DAYS)
            + " days.",
        )

    results = []
    courses = crud.get_all_courses(db)

    for course in courses:
        students = crud.get_all_students_in_course(db, course.id, course.semester)

        for student in students:
            units = crud.get_units_to_notify(
                db, student.uid, NOTIFICATION_LIMIT, course.id, course.semester
            )

            if len(units) == 0:
                continue

            try:
                message = MessageSchema(
                    subject=f"{course.id} - Missing Reflection",
                    recipients=[student.email],
                    body=format_email(student.uid, course.id, units),
                    subtype="html",
                )

                fm = FastMail(email_config)
                await fm.send_message(message)

                for unit in units:
                    crud.add_notification_count(db, student.uid, unit.id)

                results.append(
                    {
                        "course": course.id,
                        "units": [unit.id for unit in units],
                        "email": student.email,
                        "status": "success",
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "course": course.id,
                        "units": [unit.id for unit in units],
                        "email": student.email,
                        "status": "error",
                        "message": str(e),
                    }
                )
    crud.create_notification_log(db=db)
    return JSONResponse(status_code=200, content=results)


def format_email(student_id: str, course_id: str, units: List[model.Unit]):
    """
    Generates the HTML content for an email reminder to a student about providing feedback on learning units.
    """
    unit_links = [
        f'<li><a href="https://reflect.iik.ntnu.no/courseview/{unit.course_semester}/{unit.course_id}/{unit.id}">{unit.title}</a></li>'
        for unit in reversed(units)
    ]

    additional_units = (
        ""
        if len(unit_links) <= 1
        else f"<p>Also, you have not yet answered the following units:</p><ul>{''.join(unit_links[1:])}</ul>"
    )

    return f"""<p>Dear {student_id},</p>
    <p>This is a reminder to answer the recent learning unit in {course_id}:</p>
    <ul>{unit_links[0]}</ul>
    {additional_units}
    <p>Your input will directly contribute to improving the lectures for your benefit and the benefit of future students. Your feedback will be shared with your lecturer to help them tailor their teaching approach to your needs.</p>
    <p>Best regards,<br/>The Reflection Tool Team</p>"""
