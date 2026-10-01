from pydantic import BaseModel
from datetime import datetime
###plaza schema #
class PlazaCreate(BaseModel):
    plaza_name: str
    # created_by: int


class PlazaUpdate(BaseModel):
    plaza_name: str
    # updated_by: int


class PlazaResponse(BaseModel):
    Plaza_id: int
    Plaza_name: str
    Created_at: datetime | None = None
    Created_by: int | None = None
    deleted_at: datetime | None = None
    deleted_by: int | None = None
    Updated_at: datetime | None = None
    Updated_by: int | None = None


####vechicles
# data#########

class VehicleCreate(BaseModel):
    vehicle_number: str
    # created_by: int
    vehicle_type: str


class VehicleUpdate(BaseModel):
    vehicle_number: str
    vehicle_type: str


class VehicleResponse(BaseModel):
    Vehicle_id: int
    Vehicle_number: str
    Created_at: datetime | None = None
    Created_by: int | None = None
    deleted_at: datetime | None = None
    deleted_by: int | None = None
    Updated_at: datetime | None = None
    Updated_by: int | None = None
    Vehicle_type: str
    is_active: bool

    class config:
        from_attributes = True