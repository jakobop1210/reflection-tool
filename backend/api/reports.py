import json
import os

from backend.api.auth import is_admin
from backend.api.main import get_unit_data, save_report_endpoint
from backend.api.reflections import analyze_feedback

from . import crud
from . import schemas

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette.config import Config
from starlette.responses import Response

from fastapi.responses import FileResponse

config = Config(".env")


async def generate_report(request, ref, db):
    try:
        unit_data = await get_unit_data(
            request, ref.course_id, ref.course_semester, ref.unit_id, db
        )

        questions = [q["comment"] for q in unit_data["unit_questions"]]
        reflections = unit_data["unit"].reflections

        student_answers = {}
        for reflection in reflections:
            if reflection.user_id not in student_answers:
                student_answers[reflection.user_id] = {"answers": [reflection.body]}
            else:
                student_answers[reflection.user_id]["answers"].append(reflection.body)

        student_feedback = [
            {"answers": student_answers[student]["answers"]}
            for student in student_answers
        ]

        feedback = schemas.ReflectionJSON(
            api_key=config("OPENAI_KEY", cast=str),
            questions=questions,
            student_feedback=student_feedback,
            use_cheap_model=True,
        )

        analyze = await analyze_feedback(feedback)

        try:
            await save_report_endpoint(
                request,
                ref=schemas.AnalyzeReportCreate(
                    number_of_answers=len(student_feedback),
                    report_content=analyze,
                    unit_id=ref.unit_id,
                    course_id=ref.course_id,
                    course_semester=ref.course_semester,
                ),
                db=db,
            )
            crud.reset_reflections_count(db, ref.unit_id)
        except:
            raise HTTPException(500, detail="An error occurred while saving the report")
        return HTTPException(200, detail="Report generated and saved successfully")
    except IntegrityError as e:
        raise HTTPException(
            409, detail="An error occurred while generating the report: " + str(e)
        )


async def get_report(params, db):
    report = crud.get_report(
        db,
        course_id=params.course_id,
        unit_id=params.unit_id,
        course_semester=params.course_semester,
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


async def save_report(ref, db):
    try:
        return crud.save_report(db, report=ref.model_dump())
    except IntegrityError as e:
        raise HTTPException(
            409, detail="An error occurred while saving the report: " + str(e)
        )


async def download_file(request, ref, db):
    user = request.session.get("user")
    uid: str = user.get("uid")
    enrollment = crud.get_enrollment(db, ref.course_id, ref.course_semester, uid)
    if is_admin(db, request) or enrollment.role in ["lecturer"]:
        report = await get_report(
            request,
            params=schemas.AutomaticReport(
                course_id=ref.course_id,
                course_semester=ref.course_semester,
                unit_id=ref.unit_id,
            ),
            db=db,
        )

        try:
            report_dict = report.to_dict()
        except Exception as e:
            raise HTTPException(
                500,
                detail=f"An error occurred while generating the report, you may have not generated a report yet. Error: {str(e)}",
            )

        if config("SERVERLESS", cast=bool, default=False):
            return json.dumps(report_dict, indent=4)

        with open("report.txt", "w") as f:
            f.write(json.dumps(report_dict, indent=4))

        path = os.getcwd() + "/report.txt"
        return FileResponseWithDeletion(path, filename="report.txt")

    return Response(status_code=403)


# For deleting a unit after it has been created
class FileResponseWithDeletion(FileResponse):
    def __init__(self, path: str, filename: str, **kwargs):
        super().__init__(path, filename=filename, **kwargs)

    async def __call__(self, scope, receive, send):
        await super().__call__(scope, receive, send)
        os.remove(self.path)
