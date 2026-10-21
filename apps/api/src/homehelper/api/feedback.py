"""👍/👎 on assistant messages (spec §13.2, M4-08)."""

from fastapi import APIRouter, HTTPException, status

from homehelper.api.deps import SessionDep, UserDep
from homehelper.api.schemas import FeedbackCreate, FeedbackOut
from homehelper.conversations import repository

router = APIRouter(tags=["feedback"])


@router.post("/messages/{message_id}/feedback", response_model=FeedbackOut)
async def give_feedback(
    message_id: str, body: FeedbackCreate, user: UserDep, session: SessionDep
) -> FeedbackOut:
    message = await repository.get_message_for_user(session, message_id, user_id=user.id)
    if message is None or message.role != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    feedback = await repository.upsert_feedback(
        session, message.id, rating=body.rating, reason=body.reason
    )
    return FeedbackOut.model_validate(feedback)
