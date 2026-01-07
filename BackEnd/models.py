from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# Farmer: must be precise to city
class FarmerCreate(BaseModel):
    race: str
    age: int
    sex: str
    quantity: int
    state: str       # e.g. "PA"
    city: str        # e.g. "Santarém"
    contact: str
    # New fields for enhanced sale listing
    category: Optional[str] = None  # e.g., "Beef Cattle", "Dairy Cattle"
    estimated_weight: Optional[float] = None  # Estimated total weight in kg
    availability_start: Optional[str] = None  # ISO date string
    availability_end: Optional[str] = None    # ISO date string
    weight_type: Optional[str] = "live"  # "live" or "dead" (carcass weight)
    cattle_photo: Optional[str] = None
    negotiable_date: Optional[str] = None  # Legacy field for backward compatibility

class Farmer(FarmerCreate):
    id: str
    timestamp: float
    owner_id: Optional[str] = None

# Helper model: Buyer's target region
class TargetRegion(BaseModel):
    state: str       # "PA"
    city: str        # "Santarém" or "ANY" (represents entire state)

# Buyer: location becomes target region list
class BuyerCreate(BaseModel):
    targets: List[TargetRegion] # Core change: no longer a simple string list
    race: str
    ageMin: Optional[int] = 0
    ageMax: Optional[int] = 100
    sex: str
    quantity: int
    contact: str

class Buyer(BuyerCreate):
    id: str
    timestamp: float
    owner_id: Optional[str] = None