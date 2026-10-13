from fastapi import APIRouter, HTTPException, Query
from database import search_chunks
from services.extraction import embed_query

router = APIRouter(prefix="/api/search", tags=["Semantic Search"])

@router.get("")
def semantic_search(q: str = Query(..., min_length=2), limit: int = Query(5, ge=1, le=20)):
    try:
        vector = embed_query(q)
        results = search_chunks(vector, limit)
        return {"query": q, "results": results}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
