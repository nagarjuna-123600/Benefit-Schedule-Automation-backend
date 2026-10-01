
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

security = HTTPBearer()

SECRET_KEY = "Grevience-Management-System-Hyderabad-Growth-Corridor-Limited-Authentication-Key-2026",
ALGORITHM = "HS256"
ISSUER = "GMS"
AUDIENCE = "GMSUsers"


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            audience=AUDIENCE
        )

        current_user = payload.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier")

        if current_user is None:
            raise HTTPException(
                status_code=401,
                detail="User ID not found in token"
            )

        return int(current_user)

    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )