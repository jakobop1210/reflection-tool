from datetime import date

from backend.api.auth import is_admin
from prompting.enforceUniqueCategories import enforce_unique_categories
from prompting.summary import createSummary
from prompting.transformKeysToAnswers import transformKeysToAnswers
from prompting.sort import sort
from prompting.createCategories import createCategories

from . import crud

from fastapi import HTTPException


def create_reflection(ref, db):
    unit = crud.get_unit(db, ref.unit_id)
    if unit is None:
        raise HTTPException(404, detail="Unit cannot be found")

    if crud.get_question(db, ref.question_id) is None:
        raise HTTPException(404, detail="Question cannot be found")

    if unit.hidden:
        raise HTTPException(403, detail="Unit cannot be reflected when hidden")

    if crud.user_already_reflected_on_question(
        db, ref.unit_id, ref.user_id, ref.question_id
    ):
        raise HTTPException(403, detail="You have already reflected this question")

    if unit.date_available > date.today():
        raise HTTPException(403, detail="This unit is not available")

    return crud.create_reflection(db, reflection_data=ref.dict())


def delete_reflection(db, ref, request):
    if is_admin(db, request):
        return crud.delete_reflection(db, ref.user_id, ref.unit_id)
    else:
        raise HTTPException(
            403, detail="You do not have permission to delete this reflection"
        )


async def analyze_feedback(ref):
    # Adds a key to each student feedback dict to identify the student and filter out irrelevant information
    student_feedback_dicts = [
        {
            **{"key": index + 1},
            **{
                key: item[key]
                for key in item
                if key not in ["learning_unit", "participation"]
            },
        }
        for index, item in enumerate(
            (item.model_dump() for item in ref.student_feedback)
        )
    ]

    categories = createCategories(
        ref.api_key, ref.questions, student_feedback_dicts, ref.use_cheap_model
    )

    sorted_feedback = sort(
        ref.api_key,
        ref.questions,
        categories,
        student_feedback_dicts,
        ref.use_cheap_model,
    )

    sorted_feedback = enforce_unique_categories(sorted_feedback)

    stringAnswered = transformKeysToAnswers(
        sorted_feedback, ref.questions, student_feedback_dicts
    )

    summary = createSummary(ref.api_key, stringAnswered, ref.use_cheap_model)
    stringAnswered["Summary"] = summary["summary"]

    return stringAnswered
