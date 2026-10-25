"""Applications board, table and CSV export."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.deps import DbDep
from app.tracker import service as tracker

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("")
async def board(db: DbDep):
    return tracker.board(db)


@router.get("/export.csv", response_class=PlainTextResponse)
async def export(db: DbDep):
    return PlainTextResponse(
        tracker.export_csv(db),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="applications.csv"'},
    )


class ApplicationPatch(BaseModel):
    status: Literal["saved", "applied", "interviewing", "offer", "rejected", "withdrawn",
                    "archived"] | None = None  # fmt: skip
    notes: str | None = Field(None, max_length=5000)


@router.patch("/{app_id}")
async def patch(db: DbDep, app_id: int, body: ApplicationPatch):
    try:
        app = tracker.get(db, app_id)
        if body.status:
            result = tracker.set_status(db, app["job_id"], body.status)
            app = result["application"]
            app["previous_status"] = result["previous_status"]
        if body.notes is not None:
            app = {**tracker.set_notes(db, app_id, body.notes), **{
                "previous_status": app.get("previous_status")}}  # fmt: skip
        return app
    except tracker.TrackerError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/{app_id}/events")
async def events(db: DbDep, app_id: int):
    return tracker.events(db, app_id)
