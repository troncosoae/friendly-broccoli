from datetime import datetime
import os
import uuid
from typing import List, Dict, Optional, Set

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status, APIRouter
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ValidationError
import httpx # Import httpx for making asynchronous HTTP requests

# Load environment variables
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "team_admin")
TEAM_MEMBERS_SERVICE_URL = os.getenv("TEAM_MEMBERS_SERVICE_URL", "http://team_members_api:80") # URL of your main.py service

# Collection names (ensure these match your main.py if you're using shared DB)
BALL_COLLECTORS_COLLECTION = "ball_collectors"
# Note: team_members and teams collections are still initialized for direct access
# in this service for its own operations if needed, but validation now goes via API.
TEAM_MEMBERS_COLLECTION = "team_members"
TEAM_COLLECTION = "teams"


VERSION = "1.0.0"

# Initialize FastAPI app for the Ball Collectors Service
app = FastAPI(
    title="Ball Collectors Service",
    description="Manages ball collection responsibilities for teams and team members."
)

v1_router = APIRouter(prefix="/v1", tags=["v1"])

# MongoDB Client Initialization (for ball_collectors collection specifically)
client = AsyncIOMotorClient(MONGODB_URI)
mg_db = client[DB_NAME]
ball_collectors_collection = mg_db[BALL_COLLECTORS_COLLECTION]
# Keep these initialized for potential future direct use, but validation now uses API
team_members_collection = mg_db[TEAM_MEMBERS_COLLECTION]
teams_collection = mg_db[TEAM_COLLECTION]


# Pydantic models for Ball Collection
class BallCollectionBase(BaseModel):
    responsible_id: str = Field(..., description="ID of the team member responsible for ball collection.")
    team_id: str = Field(..., description="ID of the team this responsibility is attached to.")
    start_date: datetime = Field(..., description="Start date and time of the responsibility period.")
    end_date: datetime = Field(..., description="End date and time of the responsibility period.")

class BallCollectionCreate(BallCollectionBase):
    pass

class BallCollectionUpdate(BaseModel):
    responsible_id: Optional[str] = Field(None, description="New ID of the team member responsible for ball collection.")
    team_id: Optional[str] = Field(None, description="New ID of the team this responsibility is attached to.")
    start_date: Optional[datetime] = Field(None, description="New start date and time of the responsibility period.")
    end_date: Optional[datetime] = Field(None, description="New end date and time of the responsibility period.")

class BallCollectionInDB(BallCollectionBase):
    id: str = Field(..., description="Unique ID of the ball collection responsibility.")
    assigned_date: datetime = Field(..., description="Timestamp when the responsibility was assigned.")
    created_at: datetime = Field(..., description="Timestamp when the responsibility record was created.")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when the responsibility record was last updated.")

@app.on_event("startup")
async def startup_event():
    """
    Prints startup information when the service starts.
    """
    print(f"Ball Collectors Service started. Connecting to database at {MONGODB_URI} with DB name {DB_NAME}")
    print(f"Collections: {BALL_COLLECTORS_COLLECTION}")
    print(f"Validating against Team Members Service at: {TEAM_MEMBERS_SERVICE_URL}")


@app.get("/")
async def root():
    """
    Root endpoint for the service.
    """
    return {"message": "Ball Collectors Service is running!"}

@app.get("/health", summary="Health Check",
          description="Checks the health of the Ball Collectors Service.")
async def health_check():
    """
    Health check endpoint to verify the service is running.
    """
    return {"status": "ok", "service": "Ball Collectors Service", "version": VERSION}

# --- Validation Helpers (now calling external API) ---

async def _validate_team_exists(team_id: str):
    """
    Helper to validate if a team exists by calling the external Team Members Service API.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{TEAM_MEMBERS_SERVICE_URL}/v1/teams/{team_id}")
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            return response.json() # Return the team data if found
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Team with ID '{team_id}' not found via external service."
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error validating team with ID '{team_id}': {e.response.text}"
                )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not connect to Team Members Service ({TEAM_MEMBERS_SERVICE_URL}) to validate team: {e}"
            )

async def _validate_team_member_exists(member_id: str):
    """
    Helper to validate if a team member exists by calling the external Team Members Service API.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{TEAM_MEMBERS_SERVICE_URL}/v1/members/{member_id}")
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            return response.json() # Return the member data if found
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Team member with ID '{member_id}' not found via external service."
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error validating team member with ID '{member_id}': {e.response.text}"
                )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not connect to Team Members Service to validate team member: {e}"
            )

async def _validate_member_in_team(member_id: str, team_id: str):
    """
    Helper to validate if a team member belongs to a specific team, using data from API.
    """
    member_data = await _validate_team_member_exists(member_id) # This already raises HTTPException if member not found
    
    # The 'team_ids' field from the external service response should be a list
    if team_id not in member_data.get("team_ids", []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Team member '{member_id}' is not part of team '{team_id}'. Cannot assign responsibility."
        )

def _validate_dates(start_date: datetime, end_date: datetime):
    """Helper to validate that start_date is before end_date."""
    if start_date >= end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End date must be after start date."
        )

# --- Ball Collection CRUD Operations ---

@v1_router.post("/ball-collections", response_model=BallCollectionInDB, status_code=status.HTTP_201_CREATED,
          summary="Create a new ball collection assignment",
          description="Assigns a team member to ball collection duties for a specific team and period.")
async def create_ball_collection(ball_collection: BallCollectionCreate):
    """
    Creates a new ball collection assignment.

    - **responsible_id**: The ID of the team member responsible.
    - **team_id**: The ID of the team this responsibility is for.
    - **start_date**: The start date and time of the responsibility.
    - **end_date**: The end date and time of the responsibility.
    """
    # Validate existence of team and team member via API calls
    await _validate_team_exists(ball_collection.team_id)
    await _validate_team_member_exists(ball_collection.responsible_id)

    # Validate that the team member is part of the specified team via API data
    await _validate_member_in_team(ball_collection.responsible_id, ball_collection.team_id)

    # Validate date consistency
    _validate_dates(ball_collection.start_date, ball_collection.end_date)

    assignment_id = str(uuid.uuid4())
    assignment_data = ball_collection.model_dump()
    assignment_data["id"] = assignment_id
    assignment_data["assigned_date"] = datetime.utcnow()
    assignment_data["created_at"] = datetime.utcnow()
    assignment_data["updated_at"] = None

    await ball_collectors_collection.insert_one(assignment_data)
    created_assignment = await ball_collectors_collection.find_one({"id": assignment_id})
    return BallCollectionInDB(**created_assignment)

@v1_router.get("/ball-collections", response_model=List[BallCollectionInDB],
          summary="Get all ball collection assignments",
          description="Retrieves a list of all ball collection assignments, optionally filtered by team or responsible member.")
async def get_all_ball_collections(
    team_id: Optional[str] = None,
    responsible_id: Optional[str] = None
):
    """
    Retrieves all ball collection assignments, with optional filters.

    - **team_id**: Optional filter by team ID.
    - **responsible_id**: Optional filter by responsible team member ID.
    """
    query_filter = {}
    if team_id:
        # Validate team_id via API if provided as a filter
        await _validate_team_exists(team_id)
        query_filter["team_id"] = team_id
    if responsible_id:
        # Validate responsible_id via API if provided as a filter
        await _validate_team_member_exists(responsible_id)
        query_filter["responsible_id"] = responsible_id

    assignments = await ball_collectors_collection.find(query_filter).to_list(length=None)
    # Limit to 100 assignments for performance, can be paginated in a real app
    if len(assignments) > 100:
        assignments = assignments[:100]
    return [BallCollectionInDB(**assignment) for assignment in assignments]

@v1_router.get("/ball-collections/{assignment_id}", response_model=BallCollectionInDB,
          summary="Get a ball collection assignment by ID",
          description="Retrieves a specific ball collection assignment by its unique ID.")
async def get_ball_collection(assignment_id: str):
    """
    Retrieves a single ball collection assignment by its ID.

    - **assignment_id**: The unique ID of the assignment.
    """
    assignment = await ball_collectors_collection.find_one({"id": assignment_id})
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ball collection assignment not found")
    return BallCollectionInDB(**assignment)

@v1_router.put("/ball-collections/{assignment_id}", response_model=BallCollectionInDB,
          summary="Update a ball collection assignment",
          description="Updates an existing ball collection assignment. Only provided fields will be updated.")
async def update_ball_collection(assignment_id: str, assignment_update: BallCollectionUpdate):
    """
    Updates an existing ball collection assignment.

    - **assignment_id**: The unique ID of the assignment to update.
    - **responsible_id**: New responsible team member ID (optional).
    - **team_id**: New team ID (optional).
    - **start_date**: New start date (optional).
    - **end_date**: New end date (optional).
    """
    existing_assignment = await ball_collectors_collection.find_one({"id": assignment_id})
    if not existing_assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ball collection assignment not found")

    update_data = assignment_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update.")

    # Determine current values for validation, prioritizing update_data if present
    current_responsible_id = update_data.get("responsible_id", existing_assignment["responsible_id"])
    current_team_id = update_data.get("team_id", existing_assignment["team_id"])
    current_start_date = update_data.get("start_date", existing_assignment["start_date"])
    current_end_date = update_data.get("end_date", existing_assignment["end_date"])

    # Validate responsible_id and team_id if they are being updated or if they are required for cross-validation
    if "responsible_id" in update_data or "team_id" in update_data:
        await _validate_team_member_exists(current_responsible_id)
        await _validate_team_exists(current_team_id)
        # Re-validate member in team if either responsible_id or team_id changed
        await _validate_member_in_team(current_responsible_id, current_team_id)

    # Validate dates if they are being updated or if cross-validation requires it
    if "start_date" in update_data or "end_date" in update_data:
        _validate_dates(current_start_date, current_end_date)

    update_data["updated_at"] = datetime.utcnow()

    updated_assignment = await ball_collectors_collection.find_one_and_update(
        {"id": assignment_id},
        {"$set": update_data},
        return_document=True
    )

    if not updated_assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ball collection assignment not found after update attempt.")
    return BallCollectionInDB(**updated_assignment)

@v1_router.delete("/ball-collections/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a ball collection assignment",
            description="Deletes a ball collection assignment from the database by its unique ID.")
async def delete_ball_collection(assignment_id: str):
    """
    Deletes a ball collection assignment.

    - **assignment_id**: The unique ID of the assignment to delete.
    """
    assignment = await ball_collectors_collection.find_one({"id": assignment_id})
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ball collection assignment not found")

    result = await ball_collectors_collection.delete_one({"id": assignment_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ball collection assignment not found for deletion.")
    return

app.include_router(v1_router)
