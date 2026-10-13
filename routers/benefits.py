from fastapi import APIRouter, HTTPException
from database import get_document, list_benefits

router = APIRouter(prefix="/api/benefits", tags=["Benefits"])

@router.get("/by-document/{document_id}")
def get_benefits_by_document(document_id: int):
    if not get_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"document_id": document_id, "benefits": list_benefits(document_id)}
