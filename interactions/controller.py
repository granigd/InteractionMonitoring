from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from config import get_db, validate_api_key
from interactions.model import InteractionModel
from interactions.schema import BatchRequest
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status, APIRouter

router = APIRouter()


@router.post("/interactions", status_code=status.HTTP_200_OK)
async def receive_interactions(request: Request, db: AsyncSession = Depends(get_db), auth: bool = Depends(validate_api_key)):
    # Peek at raw JSON
    raw = await request.body()
    print("Raw incoming JSON:", raw.decode("utf-8"))

    # Then still parse into your Pydantic model (so
    # you get your BatchRequest validations, etc.)
    payload = await request.json()
    batch = BatchRequest(**payload)


    records = []
    for item in batch.interactions:
        rec = InteractionModel(
            time=item.timestamp,
            session_id=item.sessionId,
            action_kind=item.actionKind,
            payload=item.payload or None,
            client_id=item.clientId,
            metadata_json=item.metadata or None,
            user_agent=item.userAgent,
            url=item.url,
            source=item.source,
            batch_id=batch.batchId
        )
        records.append(rec)
    db.add_all(records)
    try:
        await db.commit()
    except Exception as ex:
        print(ex)
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to store interactions")
    return {"received": len(records), "batchId": batch.batchId, "processed": True}
