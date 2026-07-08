from datetime import date, datetime, time

from pydantic import BaseModel, EmailStr, Field

from app.models import LabStatus, ReservationStatus, UserRole


class MessageOut(BaseModel):
    success: bool
    message: str


class CaptchaOut(BaseModel):
    success: bool = True
    question: str


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8)
    captcha_answer: int
    csrf_token: str
    # Hidden honeypot field: real users never fill this in.
    website: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResult(BaseModel):
    success: bool
    require_2fa: bool
    message: str | None = None


class Verify2FARequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    role: UserRole

    model_config = {"from_attributes": True}


class LabOut(BaseModel):
    id: int
    name: str
    description: str | None
    status: LabStatus
    queue_count: int

    model_config = {"from_attributes": True}


class LabCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)


class ReservationCreate(BaseModel):
    lab_id: int
    reservation_date: date
    reservation_time: time


class JoinQueueRequest(BaseModel):
    lab_id: int


class ReservationOut(BaseModel):
    id: int
    lab_id: int
    lab_name: str
    reservation_date: date | None
    reservation_time: time | None
    status: ReservationStatus
    queue_position: int
    created_at: datetime

    model_config = {"from_attributes": True}
