"""Data models for flights and status updates."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

# Two letters or digits for the airline, then 1-4 digits. Example: UA1234.
FLIGHT_NUMBER_PATTERN = r"^[A-Z0-9]{2}[0-9]{1,4}$"
# Three-letter IATA airport code. Example: ORD.
AIRPORT_PATTERN = r"^[A-Z]{3}$"


class FlightStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    BOARDING = "BOARDING"
    DELAYED = "DELAYED"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class Flight(BaseModel):
    number: str = Field(pattern=FLIGHT_NUMBER_PATTERN, examples=["UA1234"])
    origin: str = Field(pattern=AIRPORT_PATTERN, examples=["ORD"])
    destination: str = Field(pattern=AIRPORT_PATTERN, examples=["SFO"])
    departure: datetime = Field(description="Scheduled departure time, with time zone")
    status: FlightStatus = FlightStatus.SCHEDULED
    gate: str | None = Field(default=None, max_length=8, examples=["C17"])
    delay_minutes: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def origin_differs_from_destination(self) -> "Flight":
        if self.origin == self.destination:
            raise ValueError("origin and destination must be different airports")
        return self


class StatusUpdate(BaseModel):
    status: FlightStatus
    delay_minutes: int | None = Field(default=None, ge=0)
