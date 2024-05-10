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

config = Config(".env")

oauth = OAuth(config)

CONF_URL = "https://auth.dataporten.no/.well-known/openid-configuration"
SECRET_KEY = config("SECRET_KEY", cast=Secret)
CLIENT_ID = str(config("client_id", cast=Secret))
CLIENT_SECRET = str(config("client_secret", cast=Secret))


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


def check_is_admin(bearer_token):
    """
    Checks if the user is an admin by querying the Dataporten API for group memberships.
    """
    url = "https://groups-api.dataporten.no/groups/me/groups"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {bearer_token}"}

    try:
        # Using 'with' ensures the request is closed properly
        with requests.get(url, headers=headers) as resp:
            resp.raise_for_status()
            data = resp.json()

        admin_roles = {"LECTURER", "LÆRER", "HOVEDLÆRER", "KONTAKT"}
        for group in data:
            if group["membership"]["basic"] == "owner":
                return True
            if admin_roles.intersection(group["membership"]["fsroles"]):
                return True

    except requests.RequestException as e:
        raise HTTPException(500, detail="Failed to check admin status")
    except json.JSONDecodeError:
        raise HTTPException(500, detail="Failed to parse admin status")

    return False


def get_user_data(bearer_token):
    """
    This function retrieves user data from the Dataporten API using the provided bearer token.
    """
    url = "https://api.dataporten.no/userinfo/v1/userinfo"
    headers = CaseInsensitiveDict()
    headers["Accept"] = "application/json"
    headers["Authorization"] = f"Bearer {bearer_token}"
    # print(f"Bearer {bearer_token}")
    resp = requests.get(url, headers=headers)
    return str(resp.content.decode())


def is_logged_in(request):
    user = request.session.get("user")
    return user is not None


def protect_route(request: Request):
    if not is_logged_in(request):
        raise HTTPException(401, detail="You are not logged in")


def is_admin(db, request):
    if config("isAdmin", cast=bool, default=False):
        return True

    user = request.session.get("user")
    if user is None:
        return False
    uid: str = user.get("uid")
    user = crud.get_user(db, uid)
    if user is None:
        return False
    return user.admin


async def auth(request: Request, db):
    try:
        token = await oauth.feide.authorize_access_token(request)
    except OAuthError as error:
        return HTMLResponse(f"<h1>{error.error}</h1>")
    bearer_token = token.get("access_token")
    # print("bearer_token", bearer_token)
    request.session["scope"] = token.get("scope")
    request.session["bearer_token"] = bearer_token
    request.session["user_data"] = get_user_data(bearer_token)
    user = get_user_data(bearer_token)
    if user:
        user = json.loads(user)
        #  For testing purposes, we can set the user to a test user
        if config("TEST_ACCOUNT", cast=bool, default=False):
            user["uid"] = "test"
            user["mail"] = "test@mail.no"
        else:
            user["uid"] = user["uid"][0]
            user["mail"] = user["mail"][0]
        request.session["user"] = user
        email = user.get("mail")
        uid = user.get("uid")
        db_user = crud.get_user(db, uid)
        if not db_user:
            print("creating user")
            crud.create_user(
                db=db, uid=uid, user_email=email, admin=check_is_admin(bearer_token)
            )
        else:
            print("user already exists")
    else:
        print("No user data")
    return RedirectResponse(url=BASE_URL + "/login")


async def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse(url=BASE_URL + "/")


async def user(request: Request, db):
    user = request.session.get("user")
    uid: str = user.get("uid")
    user = crud.get_user(db, uid)

    for enrollment in user.enrollments:
        course = crud.get_course(db, enrollment.course_id, enrollment.course_semester)
        enrollment.course_name = course.name
        if enrollment.role not in ["lecturer", "teaching assistant"]:
            today = datetime.now().date()
            enrollment.missingUnits = [
                {"id": unit.id, "date": unit.date_available}
                for unit in crud.get_units_for_course(
                    db, enrollment.course_id, enrollment.course_semester
                )
                if unit.date_available and unit.date_available <= today
            ]
            reflected_units = {reflection.unit_id for reflection in user.reflections}
            enrollment.missingUnits = [
                unit
                for unit in enrollment.missingUnits
                if unit["id"] not in reflected_units
            ]

    if user == None:
        request.session.pop("user")
        raise HTTPException(404, detail="User not found")

    if config("isAdmin", cast=bool, default=False):
        user.admin = True

    return user
