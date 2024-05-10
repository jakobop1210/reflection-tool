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
