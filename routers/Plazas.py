from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import null
from sqlalchemy.orm import Session
from datetime import datetime
from auth import get_current_user
from database import get_db
from models import Plaza
from schemas import PlazaCreate, PlazaUpdate, PlazaResponse

router = APIRouter(
    prefix="/Plazas",
    tags=["plazas"]
)


## create plazas

@router.post("/", response_model=PlazaResponse)
def create_plaza(
    plaza: PlazaCreate,
  current_user: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    new_plaza = Plaza(
     Plaza_name=plaza.plaza_name,
     Created_by=current_user,
     Created_at=datetime.now(),
     is_active=1)

    db.add(new_plaza)
    db.commit()
    db.refresh(new_plaza)

    return new_plaza


### all plazas

@router.get("/")
def get_plazas(
    db: Session = Depends(get_db),
):
    plazas = (
        db.query(Plaza)
        .filter(Plaza.deleted_at.is_(None))
        .all()
    )

    return plazas


#### get plaza by id

@router.get("/{plaza_id}", response_model=PlazaResponse)
def get_plaza(
    plaza_id: int,
    db: Session = Depends(get_db)
):

    plaza = (
        db.query(Plaza)
        .filter(
            Plaza.Plaza_id == plaza_id,
            Plaza.deleted_at.is_(None)
        )
        .first()
    )

    if plaza is None:
        raise HTTPException(
            status_code=404,
            detail="Plaza not found"
        )

    return plaza


### update plaza

@router.put("/{plaza_id}", response_model=PlazaResponse)
def update_plaza(
    plaza_id: int,
    plaza_data: PlazaUpdate,
    db: Session = Depends(get_db),
        current_user: int = Depends(get_current_user)
):

    plaza = (
        db.query(Plaza)
        .filter(
            Plaza.Plaza_id == plaza_id,
            Plaza.deleted_at.is_(None)
        )
        .first()
    )

    if plaza is None:
        raise HTTPException(
            status_code=404,
            detail="Plaza not found"
        )

    plaza.Plaza_name = plaza_data.plaza_name
    plaza.Updated_at = datetime.now()
    plaza.Updated_by= current_user
    # plaza.Updated_by= plaza_data.updated_by
    db.commit()
    db.refresh(plaza)

    return plaza


#### delete plaza

@router.delete("/{plaza_id}")
def delete_plaza(
    plaza_id: int,
        current_user: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    plaza = (
        db.query(Plaza)
        .filter(
            Plaza.Plaza_id == plaza_id,
            Plaza.deleted_at.is_(None),
        )
        .first()
    )

    if plaza is None:
        raise HTTPException(
            status_code=404,
            detail="Plaza not found"
        )

    plaza.deleted_at = datetime.now()
    plaza.deleted_by = current_user
    # plaza.deleted_by = Plaza.deleted_by
    plaza.is_active =0

    db.commit()

    return {
        "message": "Plaza deleted successfully"
    }