from http.client import HTTPException
from backend.api import crud
from backend.api.auth import is_admin

from . import crud
from . import model
from . import schemas
from fastapi import HTTPException, Request


def to_dict(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


async def get_units(request: Request, course_id: str, course_semester: str, db):

    user = request.session.get("user")
    uid: str = user.get("uid")
    course = crud.get_course(db, course_id, course_semester)
    if course is None:
        raise HTTPException(404, detail="Course not found")

    enrollment = crud.get_enrollment(db, course_id, course_semester, uid)
    if enrollment is None:
        await crud.create_enrollment(
            db,
            role="student",
            course_id=course_id,
            course_semester=course_semester,
            uid=uid,
        )
        enrollment = crud.get_enrollment(db, course_id, course_semester, uid)
        if enrollment is None:
            raise HTTPException(401, detail="You are not enrolled in the course")

    if is_admin(db, request) or enrollment.role in ["lecturer", "teaching assistant"]:
        units = (
            db.query(model.Unit)
            .filter(
                model.Unit.course_id == course_id,
                model.Unit.course_semester == course_semester,
            )
            .all()
        )
        units = [unit.to_dict() for unit in units]
        return units
    else:
        units = (
            db.query(model.Unit)
            .filter(
                model.Unit.course_id == course_id,
                model.Unit.course_semester == course_semester,
                model.Unit.hidden == False,
            )
            .all()
        )

        units = [unit.to_dict() for unit in units]
        return units


async def create_unit(request: Request, ref: schemas.UnitCreate, db):
    user = request.session.get("user")
    uid: str = user.get("uid")
    enrollment = crud.get_enrollment(db, ref.course_id, ref.course_semester, uid)
    if enrollment is None:
        raise HTTPException(401, detail="You are not enrolled in the course")
    if is_admin(db, request) or enrollment.role in ["lecturer", "teaching assistant"]:
        return crud.create_unit(
            db=db,
            title=ref.title,
            date_available=ref.date_available,
            course_id=ref.course_id,
            course_semester=ref.course_semester,
        )
    raise HTTPException(
        403, detail="You do not have permission to edit a unit for this course"
    )


async def update_unit(request: Request, unit_id: int, ref: schemas.UnitCreate, db):
    user = request.session.get("user")
    uid: str = user.get("uid")
    unit = crud.get_unit(db, unit_id)
    if not unit:
        raise HTTPException(404, detail="Unit not found")
    enrollment = crud.get_enrollment(db, unit.course_id, unit.course_semester, uid)
    if enrollment is None:
        raise HTTPException(401, detail="You are not enrolled in the course")
    if is_admin(db, request) or enrollment.role in ["lecturer", "teaching assistant"]:
        return crud.update_unit(
            db=db,
            unit_id=unit_id,
            title=ref.title,
            date_available=ref.date_available,
            course_id=ref.course_id,
            course_semester=ref.course_semester,
        )
    raise HTTPException(
        403, detail="You do not have permission to edit a unit for this course"
    )


async def delete_unit(unit_id: int, ref: schemas.UnitDelete, request: Request, db):
    user = request.session.get("user")
    uid: str = user.get("uid")
    unit = crud.get_unit(db, unit_id)
    if not unit:
        raise HTTPException(404, detail="Unit not found")
    enrollment = crud.get_enrollment(db, unit.course_id, unit.course_semester, uid)
    if is_admin(db, request) or enrollment.role in ["lecturer"]:
        return crud.delete_unit(db, unit_id, ref.course_id, ref.course_semester)
    raise HTTPException(
        403, detail="You do not have permission to delete a unit for this course"
    )


async def get_unit_data(
    request: Request, course_id: str, course_semester: str, unit_id: int, db
):
    user = request.session.get("user")
    email: str = user.get("uid")
    course = crud.get_course(db, course_id, course_semester)
    if course is None:
        raise HTTPException(404, detail="Course not found")
    enrollment = crud.get_enrollment(db, course_id, course_semester, email)
    if enrollment is None:
        raise HTTPException(401, detail="You are not enrolled in the course")
    unit = (
        db.query(model.Unit)
        .filter(
            model.Unit.id == unit_id,
            model.Unit.course_id == course_id,
            model.Unit.course_semester == course_semester,
        )
        .first()
    )
    if unit:
        questions = [to_dict(question) for question in course.questions]

        if is_admin(db, request) or enrollment.role in [
            "lecturer",
            "teaching assistant",
        ]:
            return {
                "unit": unit,
                "unit_questions": questions,
            }
        else:
            unit = (
                db.query(model.Unit)
                .filter(
                    model.Unit.course_id == course_id,
                    model.Unit.course_semester == course_semester,
                    model.Unit.id == unit_id,
                    model.Unit.hidden == False,
                )
                .first()
            )
            if unit:
                return {
                    "unit": unit,
                    "unit_questions": questions,
                }

    raise HTTPException(404, detail="Unit not found")
