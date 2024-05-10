from typing import List

from api.utils.exceptions import DataProcessingError, OpenAIRequestError
from api import auth, reflections, reports, courses, units, notifications
from api.auth import is_admin, protect_route


from . import crud
from . import model
from . import schemas

from authlib.integrations.starlette_client import OAuth
from .database import engine, get_db
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.config import Config
from starlette.datastructures import Secret
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse


from api import database

model.Base.metadata.create_all(bind=engine)

app = FastAPI()
config = Config(".env")
oauth = OAuth(config)

CONF_URL = "https://auth.dataporten.no/.well-known/openid-configuration"
SECRET_KEY = config("SECRET_KEY", cast=Secret)
CLIENT_ID = str(config("client_id", cast=Secret))
CLIENT_SECRET = str(config("client_secret", cast=Secret))

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

app.add_middleware(
    CORSMiddleware,
    allow_origins="*",
    allow_credentials=True,
    allow_headers=["*"],
    allow_methods=["*"],
)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


def is_prod():
    return config("production", cast=bool, default=False)


if is_prod():
    REDIRECT_URI = config("REDIRECT_URI", cast=str)
    BASE_URL = config("BASE_URL", cast=str)
else:
    REDIRECT_URI = "http://127.0.0.1:8000/auth"
    BASE_URL = "http://127.0.0.1:5173"


oauth.register(
    name="feide",
    server_metdata_url=CONF_URL,
    client_kwards={"scope": "openid"},
    authorize_url="https://auth.dataporten.no/oauth/authorization",
    access_token_url="https://auth.dataporten.no/oauth/token",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
)


@app.on_event("startup")
async def start_db():
    """
    Used for creating dummy data in the database for development purposes when running locally.

    It creates a course, units, and users, and enrolls a test user in the course.
    """
    if is_prod():
        return
    return await database.start_db()


@app.get("/login")
async def login(request: Request):
    return await oauth.feide.authorize_redirect(request, REDIRECT_URI)


@app.get("/auth")
async def authenticate(request: Request, db: Session = Depends(get_db)):
    """
    This is the callback route for the OAuth2 authentication process.
    It retrieves the access token from the request and stores it in the user's session.

    Also creates a user in the database if the user does not already exist.
    """
    return await auth.auth(request, db)


@app.get("/logout")
async def logout(request: Request):
    return await auth.logout(request)


@app.post("/reflection", response_model=schemas.Reflection)
async def create_reflection(
    request: Request, ref: schemas.ReflectionCreate, db: Session = Depends(get_db)
):
    """
    Creates a reflection based on the data provided in the `ref` object.
    This saves the response a user has given to a question in a unit.
    """
    protect_route(request)
    return await reflections.create_reflection(ref, db)


@app.delete("/delete_reflection", response_model=schemas.ReflectionDelete)
async def delete_reflection(
    request: Request, ref: schemas.ReflectionDelete, db: Session = Depends(get_db)
):
    """
    Deletes a reflection based on the user ID, unit ID, and question ID provided in the `ref` object.
    """
    protect_route(request)
    return await reflections.delete_reflection(db, ref, request)


# Example: /course?course_id=TDT4100&course_semester=fall2023
@app.get("/course", response_model=schemas.Course)
async def getcourse(
    request: Request,
    course_id: str,
    course_semester: str,
    db: Session = Depends(get_db),
):
    protect_route(request)
    return courses.course(course_id, course_semester, db)


@app.get("/user", response_model=schemas.User)
async def user(request: Request, db: Session = Depends(get_db)):
    """
    Retrieves the user's data based on the user ID stored in the session.

    It will also return the users enrollments and missing units.
    """
    protect_route(request)
    return await auth.user(request, db)


@app.post("/create_course", response_model=schemas.Enrollment)
async def create_course(
    request: Request, ref: schemas.CourseCreate, db: Session = Depends(get_db)
):
    """
    Creates a course based on the data provided in the `ref` object.
    """
    protect_route(request)
    return await courses.create_course(request, ref, db)


# enroll self in course
@app.post("/enroll", response_model=schemas.Enrollment)
async def enroll(
    request: Request, ref: schemas.EnrollmentCreate, db: Session = Depends(get_db)
):
    """
    Enrolls a user in a course based on the data provided in the `ref` object.
    This will also enroll a user if they have a private invitation to the course.
    """
    protect_route(request)
    return await courses.enroll(request, ref, db)


# Example: /units?course_id=TDT4100&course_semester=fall2023
@app.get("/units", response_model=List[schemas.Unit])
async def get_units(
    request: Request,
    course_id: str,
    course_semester: str,
    db: Session = Depends(get_db),
):
    """
    Retrieves all units for a specific course based on the course ID and course semester provided.
    If a user is not enrolled in the course, they will be enrolled as a student.

    And if they are a lecturer or teaching assistant, they will see all units including the hidden ones.
    """
    protect_route(request)
    return await units.get_units(request, course_id, course_semester, db)


@app.post("/create_unit", response_model=schemas.Unit)
async def create_unit(
    request: Request, ref: schemas.UnitCreate, db: Session = Depends(get_db)
):
    """
    Creates a new unit with the unit-details from the 'ref' object, if the user-details provided in `ref` is admin.
    """
    protect_route(request)
    return await units.create_unit(request, ref, db)


@app.patch("/update_unit/{unit_id}", response_model=schemas.UnitCreate)
async def update_unit(
    unit_id: int,
    request: Request,
    ref: schemas.UnitCreate,
    db: Session = Depends(get_db),
):
    """
    Updates the details of an existing unit identified by `unit_id` with new information
    provided in the `ref` object, which includes the unit's title and date available.
    """
    protect_route(request)
    return await units.update_unit(request, unit_id, ref, db)


@app.delete("/delete_unit/{unit_id}", response_model=schemas.UnitDelete)
async def delete_unit(
    unit_id: int,
    ref: schemas.UnitDelete,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Deletes a specific unit based on the unit ID, course ID, and course semester provided, if user-details from 'ref' object is admin.
    """
    protect_route(request)
    return await units.delete_unit(request, unit_id, ref, db)


@app.get("/download")
async def download_file(
    request: Request,
    ref: schemas.AutomaticReport = Depends(),
    db: Session = Depends(get_db),
):
    """
    Retrieves a report stored in the database based on course id, unit id, and course semester provided in the `ref` object.
    Downloads the provided report file.
    """
    protect_route(request)
    return await reports.download_file(request, ref, db)


# Example: /unit_data?course_id=TDT4100&course_semester=fall2023&unit_id=1
@app.get("/unit_data", response_model=schemas.UnitData)
async def get_unit_data(
    request: Request,
    course_id: str,
    course_semester: str,
    unit_id: int,
    db: Session = Depends(get_db),
):
    """
    Retrieves a specific unit based on the course ID, course semester, and unit ID provided.
    """
    protect_route(request)
    return await units.get_unit_data(request, course_id, course_semester, unit_id, db)


# This can be uncommented to test the functionality for development purposes
# @app.post("/save_report", response_model=schemas.ReportCreate)
async def save_report_endpoint(
    request: Request, ref: schemas.ReportCreate, db: Session = Depends(get_db)
):
    if not is_admin(db, request):
        raise HTTPException(403, detail="You are not an admin user")
    return await reports.save_report(db, ref)


@app.get("/report")
async def get_report(
    request: Request,
    params: schemas.AutomaticReport = Depends(),
    db: Session = Depends(get_db),
):
    """
    Retrieve a report from the database based on the provided parameters such as course id, unit id, and course semester.
    """
    protect_route(request)
    return await reports.get_report(params, db)


@app.post("/create_invitation", response_model=schemas.Invitation)
async def create_invitation(
    request: Request, ref: schemas.InvitationBase, db: Session = Depends(get_db)
):
    """
    Creates an invitation to an user for a course based on user-details and course-details provided in the `ref` object.
    """
    protect_route(request)
    return notifications.create_invitation(request, ref, db)


# get all invitations by user
@app.get("/get_invitations", response_model=List[schemas.Invitation])
async def get_invitations(request: Request, db: Session = Depends(get_db)):
    """
    Retrieves all invitations for a user based on the user ID stored in the session.
    """
    protect_route(request)
    return notifications.get_invitations(request, db)


# delete invitation
@app.delete("/delete_invitation/{id}")
async def delete_invitation(request: Request, id: int, db: Session = Depends(get_db)):
    """
    Deletes an invitation based on the invitation ID provided.
    """
    protect_route(request)

    return crud.delete_invitation(db, id=id)


@app.post("/send-notifications")
async def send_notifications(db: Session = Depends(get_db)):
    """
    Sends reminder notifications to students about units they need to provide feedback for.

    This function iterates over all courses and their enrolled students, identifying units
    for which students have not yet reached the notification limit. It then sends a reminder
    email to each student about their pending units, updating the notification count for each unit
    per student.
    """
    return await notifications.send_notifications(db)


@app.post("/analyze_feedback")
async def analyze_feedback(ref: schemas.ReflectionJSON):
    """
    Analyzes student feedback, sorts it into predefined categories, and generates a summary.

    This function processes student feedback submitted for a learning unit. It categorizes the feedback based on the content, sorts it accordingly, and then generates a summary highlighting key themes. The process involves the following steps:
    1. Filtering relevant information from the submitted feedback.
    2. Categorizing the feedback using the OpenAI API.
    3. Sorting the feedback into the identified categories.
    4. Transforming sorted keys into actual answers for a readable format.
    5. Generating a summary of the categorized feedback.
    """

    return await reflections.analyze_feedback(ref)


@app.delete("/unenroll_course")
async def unenroll_course(
    request: Request, ref: schemas.EnrollmentBase, db: Session = Depends(get_db)
):
    """
    Unenrolls the user from a course based on the course ID and course semester provided in the `ref` object.
    """
    protect_route(request)
    return await courses.unenroll_course(request, ref, db)


@app.delete("/delete_course")
async def delete_course(
    request: Request, ref: schemas.CourseBase, db: Session = Depends(get_db)
):
    """
    Deletes a course based on the course ID and course semester provided in the `ref` object.
    """
    protect_route(request)
    return await courses.delete_course(request, ref, db)


@app.post("/generate_report")
async def generate_report(
    request: Request, ref: schemas.AutomaticReport, db: Session = Depends(get_db)
):
    """
    Generates and saves a report for a specific unit based on the course ID, course semester, and unit ID provided in the `ref` object.
    """
    if not is_admin(db, request):
        raise HTTPException(403, detail="You are not an admin user")
    return await reports.generate_report(request, ref, db)


@app.exception_handler(DataProcessingError)
async def data_processing_exception_handler(request, exc: DataProcessingError):
    return JSONResponse(
        status_code=400,
        content={"message": f"Data processing error: {exc.message}"},
    )


@app.exception_handler(OpenAIRequestError)
async def openai_request_exception_handler(request, exc: OpenAIRequestError):
    return JSONResponse(
        status_code=502,
        content={"message": f"OpenAI API request failed: {exc.message}"},
    )
