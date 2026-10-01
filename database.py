from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, declarative_base
server = ""
database = ""
username = ""
password = ""

connection_url = URL.create(
    "mssql+pyodbc",
    username=username,
    password=password,
    host="62.169.17.111",
    port=1433,
    database=database,
    query={
        "driver": "ODBC Driver 17 for SQL Server"
    }
)

engine = create_engine(connection_url)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()