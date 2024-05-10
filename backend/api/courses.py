from http.client import HTTPException
from backend.api import crud
from backend.api.auth import is_admin, protect_route
import json
import os
from datetime import datetime, date
from typing import List

import requests
from requests.structures import CaseInsensitiveDict
from api.utils.exceptions import DataProcessingError, OpenAIRequestError
from prompting.enforceUniqueCategories import enforce_unique_categories
from prompting.summary import createSummary
from prompting.transformKeysToAnswers import transformKeysToAnswers
from prompting.sort import sort
from prompting.createCategories import createCategories

from . import crud
from . import model
from . import schemas

from authlib.integrations.starlette_client import OAuth, OAuthError
from .database import SessionLocal, engine
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.config import Config
from starlette.datastructures import Secret
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse, Response, JSONResponse

from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from fastapi.responses import FileResponse


async def course(course_id: str, course_semester: str, db):
    course = crud.get_course(db, course_id=course_id, course_semester=course_semester)
    if course is None:
        raise HTTPException(404, detail="Course not found")

    print("course found")
    return course


async def create_course(request: Request, ref: schemas.CourseCreate, db):
    user = request.session.get("user")
    uid: str = user.get("uid")

    if not is_admin(db, request):
        raise HTTPException(403, detail="You are not an admin user")
    try:
        crud.create_course(db, course=ref.dict())
        return await crud.create_enrollment(
            db,
            role="lecturer",
            course_id=ref.id,
            course_semester=ref.semester,
            uid=uid,
        )

    except IntegrityError:
        raise HTTPException(409, detail="Course already exists")


async def enroll(request: Request, ref: schemas.EnrollmentCreate, db):
    course = crud.get_course(
        db, course_id=ref.course_id, course_semester=ref.course_semester
    )

    if course == None:
        raise HTTPException(404, detail="Course not found")

    user = request.session.get("user")
    uid: str = user.get("uid")
    if user is None:
        raise HTTPException(401, detail="Cannot find your user")

    invitations = crud.get_invitations(db, uid)
    if invitations is not None:
        priv_inv = crud.get_priv_invitations_course(
            db, uid, ref.course_id, ref.course_semester
        )
        if len(priv_inv) != 0 or is_admin(db, request):
            try:

                return await crud.create_enrollment(
                    db,
                    role=ref.role,
                    course_id=ref.course_id,
                    course_semester=ref.course_semester,
                    uid=uid,
                )
            except IntegrityError:
                raise HTTPException(409, detail="User already enrolled in this course")

    if ref.role == "student" or is_admin(db, request):
        try:
            return await crud.create_enrollment(
                db,
                role=ref.role,
                course_id=ref.course_id,
                course_semester=ref.course_semester,
                uid=uid,
            )
        except IntegrityError:
            raise HTTPException(409, detail="User already enrolled in this course")

    raise HTTPException(403, detail="User not allowed to enroll")


async def unenroll_course(request: Request, ref: schemas.EnrollmentBase, db):
    try:
        user = request.session.get("user")
        uid = user.get("uid")
        return crud.delete_enrollment(db, uid, ref.course_id, ref.course_semester)
    except IntegrityError:
        raise HTTPException(409, detail="Course already exists")


async def delete_course(request: Request, ref: schemas.CourseBase, db):
    if not is_admin(db, request):
        raise HTTPException(403, detail="You are not an admin user")
    try:
        return crud.delete_course(db, ref.id, ref.semester)
    except IntegrityError:
        raise HTTPException(409, detail="Course already exists")
