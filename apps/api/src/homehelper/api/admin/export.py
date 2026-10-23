"""Annotation → regression case (spec §17.2, M7-02). The case is stored in `regression_cases`;
`uv run evals regression pull` writes it into the repo, since the API can't."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Response, status

from homehelper.api.deps import SessionDep, SettingsDep, require_admin
from homehelper.api.manuals import manual_entries
from homehelper.api.schemas import RegressionExportOut, RegressionExportRequest
from homehelper.conversations import repository as conversations
from homehelper.conversations.repository import utcnow
from homehelper.core.logging import get_logger
from homehelper.db.models import RegressionCaseRow
from homehelper.quality import repository
from homehelper.quality.export import ExportChoices, ExportError, build_case, suggest
from homehelper.quality.regression import case_yaml

router = APIRouter(dependencies=[Depends(require_admin)])
log = get_logger(__name__)


@router.post(
    "/annotations/{annotation_id}/export",
    response_model=RegressionExportOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Dry run: the case it would export."}, 404: {}, 409: {}},
)
async def export_annotation(
    annotation_id: Annotated[str, Path(max_length=64)],
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    body: Annotated[RegressionExportRequest | None, Body()] = None,
    dry_run: bool = False,
) -> RegressionExportOut:
    """Export once; the annotation is frozen afterwards. `dry_run` only previews the case."""
    body = body or RegressionExportRequest()
    annotation = await repository.get_annotation(session, annotation_id, for_update=True)
    if annotation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found")
    if annotation.exported_case_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Already exported as {annotation.exported_case_id}"
        )
    message = await repository.get_message(session, annotation.message_id)
    found = await repository.get_conversation(session, message.conversation_id) if message else None
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The conversation was deleted")
    conversation, user = found

    suggestion = suggest(annotation.issue_types, annotation.expected_response)
    choices = ExportChoices(
        expected_outcomes=(
            suggestion.expected_outcomes
            if body.expected_outcomes is None
            else body.expected_outcomes
        ),
        expected_doc_id=body.expected_doc_id,
        assertions=body.assertions or suggestion.assertions,
    )
    if choices.expected_doc_id and choices.expected_doc_id not in manual_entries(
        settings.manuals_dir
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown manual")
    rows = await conversations.list_messages(session, conversation.id)
    attachments = await conversations.attachments_by_message(session, [m.id for m in rows])
    try:
        exported = build_case(
            conversation=conversation,
            user=user,
            messages=rows,
            attachments=attachments,
            annotation=annotation,
            choices=choices,
            exported_at=utcnow(),
        )
    except ExportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    case = exported.case
    out = RegressionExportOut(case=case, yaml=case_yaml(case), exported=not dry_run)
    if dry_run:
        response.status_code = status.HTTP_200_OK
        return out
    await repository.add_regression_case(
        session,
        RegressionCaseRow(
            id=case.id,
            annotation_id=annotation.id,
            conversation_id=conversation.id,
            message_id=annotation.message_id,
            case=case.model_dump(mode="json"),
            media_sources=exported.media_sources,
        ),
    )
    annotation.exported_case_id = case.id
    await session.flush()
    log.info("admin_annotation_exported", annotation_id=annotation.id, case_id=case.id)
    return out
