from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import null
from sqlalchemy.orm import Session
from datetime import datetime

from sqlalchemy.sql.functions import current_user

from auth import get_current_user
from database import get_db
from models import Vehicle
from schemas import VehicleCreate, VehicleUpdate, VehicleResponse

router = APIRouter(
    prefix="/Vehicles",
    tags=["Vehicles"]
)


#craete Vehicles

@router.post("/", response_model=VehicleResponse)
def create_vehicle(
    vehicle: VehicleCreate,
current_user: int = Depends(get_current_user),

    db: Session = Depends(get_db)
):

    new_Vehicle = Vehicle(
        Vehicle_number=vehicle.vehicle_number,
        Created_by=current_user,
        # Created_by=vehicle.created_by,
        Created_at=datetime.now(),
        Vehicle_type=vehicle.vehicle_type,
        is_active=1
    )

    db.add(new_Vehicle)
    db.commit()
    db.refresh(new_Vehicle)

    return new_Vehicle

# all vehicles

@router.get("/", response_model=list[VehicleResponse])
def get_vehicle(
    db: Session = Depends(get_db),
):
    Vehicles = (
        db.query(Vehicle)
        .filter(Vehicle.deleted_at.is_(None))
        .all()
    )

    return Vehicles

# vehicles by number

@router.get("/{vehicle_id}", response_model=VehicleResponse)
def get_vehicles(
    vehicle_id: int,
    db: Session = Depends(get_db)
):

    Vehicles = (
        db.query(Vehicle)
        .filter(
            Vehicle.Vehicle_id == vehicle_id,
            Vehicle.deleted_at.is_(None)
        )
        .first()
    )

    if Vehicles is None:
        raise HTTPException(
            status_code=404,
            detail="vehicle not found"
        )

    return Vehicles


###### update plaza

@router.put("/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: int,
    vehicle_data: VehicleUpdate,
current_user: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    Vehicles = (
        db.query(Vehicle)
        .filter(
            Vehicle.Vehicle_id == vehicle_id,
            Vehicle.deleted_at.is_(None)
        )
        .first()
    )

    if Vehicles is None:
        raise HTTPException(
            status_code=404,
            detail="Vehicle not found"
        )

    Vehicles.Vehicle_number = vehicle_data.vehicle_number
    Vehicles.Updated_at = datetime.now()
    Vehicles.Updated_by = current_user
    # Vehicles.Updated_by = Vehicle.Updated_by
    Vehicles.Vehicle_type = vehicle_data.vehicle_type
    db.commit()
    db.refresh(Vehicles)

    return Vehicles

# delete vehicles

@router.delete("/{vehicle_id}")
def delete_vehicle(
    vehicle_id: int,
current_user: int = Depends(get_current_user),
    db: Session = Depends(get_db)
):

    vehicles = (
        db.query(Vehicle)
        .filter(
            Vehicle.Vehicle_id == vehicle_id,
            Vehicle.deleted_at.is_(None),
        )
        .first()
    )

    if vehicles is None:
        raise HTTPException(
            status_code=404,
            detail="vehicle not found"
        )

    vehicles.deleted_at = datetime.now()
    vehicles.deleted_by = current_user
    # vehicles.Updated_by = Vehicle.Updated_by
    vehicles.is_active=0
    db.commit()

    return {
        "message": "vehicle deleted successfully"
    }