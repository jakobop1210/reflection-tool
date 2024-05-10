from http.client import HTTPException
from backend.api import crud
from backend.api.auth import is_admin
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


from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from starlette.config import Config
from starlette.datastructures import Secret

# Selects which DB to use based on the environment

config = Config(".env")

if config("production", cast=bool, default=False):
    DATABASE_URI = str(config("DATABASE_URI", cast=Secret))
    engine = create_engine(DATABASE_URI)
else:
    if config("TEST", cast=bool, default=False):
        DATABASE_URL = "sqlite:///./test.db"
    else:
        DATABASE_URL = "sqlite:///./reflect.db"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db

    finally:
        db.close()


async def start_db():
    print("init database")
    course_id: str = "TDT4100"
    semester: str = "fall2023"
    course_name: str = "Informasjonsteknologi grunnkurs"
    db = SessionLocal()
    course = crud.get_course(db, course_id=course_id, course_semester=semester)
    if course:
        return

    course = crud.create_course(
        db,
        course={
            "name": course_name,
            "id": course_id,
            "semester": semester,
            "questions": [],
        },
    )

    UID = config("UID", cast=str, default="test")
    EMAIL_USER = config("EMAIL_USER", cast=str, default="test@test.no")

    user = crud.create_user(db, uid=UID, user_email=EMAIL_USER)
    user0 = crud.create_user(db, uid="test2", user_email="test2@test.no")
    user1 = crud.create_user(db, uid="test3", user_email="test3@test.no")

    units = [
        crud.create_unit(
            db=db,
            title="State Machines",
            date_available=datetime(2022, 8, 23),
            course_id=course.id,
            course_semester=semester,
        ),
        crud.create_unit(
            db=db,
            title="HTTP og JSON",
            date_available=datetime(2022, 8, 30),
            course_id=course.id,
            course_semester=semester,
        ),
        crud.create_unit(
            db=db,
            title="MQTT Chat",
            date_available=datetime(2024, 9, 7),
            course_id=course.id,
            course_semester=semester,
        ),
    ]

    for u in units:
        course.units.append(u)
        u.course_id = course.id
        u.course_semester = semester

    await crud.create_enrollment(
        db=db,
        course_id="TDT4100",
        course_semester=semester,
        role="student",
        uid=UID,
    )

    db.commit()
    db.close()
