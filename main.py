from fastapi import FastAPI
from routers.Plazas import router as plaza_router
from routers.Vehicles import router as Vehicle_router
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(plaza_router)
app.include_router(Vehicle_router)


@app.get("/")
def home():
    return {
        "message": "Grievance Backend API is running"
    }