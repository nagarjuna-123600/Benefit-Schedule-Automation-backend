
from sqlalchemy import Column, Integer, String, DateTime,Boolean
from database import Base


class Plaza(Base):

    __tablename__ = "Plazas"

    Plaza_id = Column(Integer, primary_key=True, index=True)

    Plaza_name = Column(String(255), nullable=False)

    Created_at = Column(DateTime, nullable=False)

    deleted_at = Column(DateTime, nullable=True)

    Updated_at = Column(DateTime, nullable=True)

    Created_by = Column(Integer, nullable=True)

    Updated_by = Column(Integer, nullable=True)

    deleted_by = Column(Integer, nullable=True)

    is_active =Column(Integer, nullable=False)

class Vehicle(Base):

    __tablename__ = "Vehicles"

    Vehicle_id = Column(Integer, primary_key=True, index=True)

    Vehicle_number = Column(String(30), nullable=False)

    Vehicle_type = Column(String(100), nullable=False)

    is_active = Column(Boolean, nullable=False)

    Created_at = Column(DateTime, nullable=False)

    Created_by = Column(Integer,  nullable=True)

    Updated_at = Column(DateTime, nullable=True)

    Updated_by = Column(Integer, nullable=True)

    deleted_at = Column(DateTime, nullable=True)

    deleted_by = Column(Integer, nullable=True)