# services/ball_collectors/main.py

from datetime import datetime, date, timedelta
from enum import Enum
import os
from typing import List, Dict
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, root_validator
import httpx # Import httpx for making HTTP requests to other services

# Load environment variables
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "team_admin")
COLLECTION = "ball_collectors" # Collection name for ball collector assignments

# URL for the Team Members Service (as defined in docker-compose.yml)
# This will be used for inter-service communication
TEAM_MEMBERS_SERVICE_URL = os.getenv("TEAM_MEMBERS_SERVICE_URL", "http://team_members_api:80")

VERSION = "1.0.0"

# Initialize FastAPI app
app = FastAPI(
    title="Ball Collectors Service",
    description="Manages weekly ball carrier assignments and sends reminders."
)

# Initialize MongoDB client
client = AsyncIOMotorClient(MONGODB_URI)
mg_db = client[DB_NAME]
ball_carrier_assignments_collection = mg_db[COLLECTION]

# Pydantic models
class BallCarrierAssignmentBase(BaseModel):
    member_id: str
    assignment_date: date = Field(..., description="Date for which the assignment is valid (e.g., start of the week).")

class BallCarrierAssignmentCreate(BallCarrierAssignmentBase):
    pass

class BallCarrierAssignmentInDB(BallCarrierAssignmentBase):
    id: str

    # This validator converts the datetime object (from MongoDB) to a date object for the Pydantic model
    @root_validator(pre=True)
    def convert_mongo_datetime_to_date(cls, values):
        if 'assignment_date' in values and isinstance(values['assignment_date'], datetime):
            values['assignment_date'] = values['assignment_date'].date()
        return values

# Helper function to check if a team member exists in the Team Members Service
async def check_team_member_exists(member_id: str):
    """
    Checks if a team member with the given ID exists by querying the Team Members Service.
    Raises HTTPException if the member does not exist or if the Team Members Service is unreachable.
    """
    async with httpx.AsyncClient() as client:
        try:
            # Construct the URL to the Team Members Service's member endpoint
            response = await client.get(f"{TEAM_MEMBERS_SERVICE_URL}/members/{member_id}")
            response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
            return response.json() # Return the member data if found
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, # 400 Bad Request for invalid input ID
                    detail=f"Team member with ID '{member_id}' does not exist in the Team Members Service."
                )
            # Re-raise other HTTP errors as internal server error
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error checking Team Members Service: {e.response.text} (Status: {e.response.status_code})"
            )
        except httpx.RequestError as e:
            # Handle network or connection errors
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not connect to Team Members Service at {TEAM_MEMBERS_SERVICE_URL}: {e}"
            )


@app.on_event("startup")
async def startup_event():
    print(f"Ball Collectors Service started.")
    print(f"Connecting to database at {MONGODB_URI} with DB name {DB_NAME} and collection {COLLECTION}")
    # Optional: You might want to check the MongoDB connection here
    try:
        await mg_db.command("ping")
        print("Successfully connected to MongoDB.")
    except Exception as e:
        print(f"Failed to connect to MongoDB: {e}")
        # In a real application, you might want to exit or log a critical error


@app.get("/")
async def root():
    return {"message": "Ball Collectors Service is running!"}

@app.get("/health", summary="Health Check",
            description="Checks the health of the Ball Collectors Service.")
async def health_check():
    """
    Health check endpoint to verify the service is running and connected to MongoDB.
    """
    try:
        await mg_db.command("ping") # Check MongoDB connection
        mongo_status = "ok"
    except Exception:
        mongo_status = "error"
    return {"status": "ok", "service": "Ball Collectors Service", "version": VERSION, "mongodb_status": mongo_status}

@app.post("/assignments", response_model=BallCarrierAssignmentInDB, status_code=status.HTTP_201_CREATED,
          summary="Create a new ball carrier assignment",
          description="Assigns a team member as a ball carrier for a specific date (e.g., start of the week).")
async def create_ball_carrier_assignment(assignment: BallCarrierAssignmentCreate):
    """
    Creates a new ball carrier assignment.

    - **member_id**: The ID of the team member assigned. This ID will be verified against the Team Members Service.
    - **assignment_date**: The date for which the assignment is valid.
    """
    # Verify if the member_id exists in the Team Members Service
    await check_team_member_exists(assignment.member_id)

    # Convert Pydantic date to datetime at midnight UTC for MongoDB storage
    assignment_datetime = datetime.combine(assignment.assignment_date, datetime.min.time())

    assignment_id = str(uuid.uuid4())
    assignment_data = assignment.model_dump()
    assignment_data["id"] = assignment_id
    assignment_data["assignment_date"] = assignment_datetime # Store as datetime

    # Check for existing assignment for the same member on the same date (optional, but good for uniqueness)
    existing_assignment = await ball_carrier_assignments_collection.find_one({
        "member_id": assignment_data["member_id"],
        "assignment_date": assignment_datetime
    })
    if existing_assignment:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An assignment for this member on this date already exists."
        )

    await ball_carrier_assignments_collection.insert_one(assignment_data)
    # Retrieve the inserted document to ensure it matches the InDB model, including the ID
    inserted_assignment = await ball_carrier_assignments_collection.find_one({"id": assignment_id})
    if not inserted_assignment:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve inserted assignment.")

    print(f"Created ball carrier assignment for member {assignment_data['member_id']} on {assignment.assignment_date}")
    return BallCarrierAssignmentInDB(**inserted_assignment)

@app.get("/assignments/current", response_model=List[BallCarrierAssignmentInDB],
          summary="Get current week's ball collectors",
          description="Retrieves ball collectors assigned for the current week.")
async def get_current_ball_collectors():
    """
    Retrieves ball collectors whose assignment date falls within the current week.
    The current week is defined as starting from today.
    """
    today = date.today()
    # Define the start of the current week (e.g., Monday of the current week)
    # For simplicity here, we'll consider "current week" as assignments from today up to the next 7 days
    start_of_period = datetime.combine(today, datetime.min.time())
    end_of_period = datetime.combine(today + timedelta(days=7), datetime.min.time())

    # Query MongoDB for assignments within the current week
    assignments = await ball_carrier_assignments_collection.find({
        "assignment_date": {
            "$gte": start_of_period,
            "$lt": end_of_period
        }
    }).to_list(length=None)

    # Verify existence of each member_id for the fetched assignments
    # In a real scenario, you might do this only when displaying, or cache results
    verified_assignments = []
    for assignment_doc in assignments:
        try:
            # We don't need the full response, just to check existence
            await check_team_member_exists(assignment_doc["member_id"])
            verified_assignments.append(BallCarrierAssignmentInDB(**assignment_doc))
        except HTTPException as e:
            print(f"Warning: Assignment {assignment_doc.get('id')} has an invalid member_id {assignment_doc['member_id']}: {e.detail}")
            # Optionally, you might log this or skip this assignment

    return verified_assignments

@app.get("/assignments/upcoming", response_model=List[BallCarrierAssignmentInDB],
          summary="Get upcoming ball carrier assignments",
          description="Retrieves all ball carrier assignments scheduled for the future.")
async def get_upcoming_ball_collectors():
    """
    Retrieves all upcoming ball carrier assignments.
    """
    today_datetime = datetime.combine(date.today(), datetime.min.time())

    # Query MongoDB for assignments with an assignment_date greater than today
    assignments = await ball_carrier_assignments_collection.find({
        "assignment_date": {"$gt": today_datetime}
    }).to_list(length=None)

    upcoming_assignments = [BallCarrierAssignmentInDB(**assign) for assign in assignments]
    # Sort by assignment date (Pydantic models will have 'date' objects, which are comparable)
    upcoming_assignments.sort(key=lambda x: x.assignment_date)

    # Optional: Verify existence of each member_id for the fetched assignments
    verified_upcoming_assignments = []
    for assignment_item in upcoming_assignments:
        try:
            await check_team_member_exists(assignment_item.member_id)
            verified_upcoming_assignments.append(assignment_item)
        except HTTPException as e:
            print(f"Warning: Upcoming assignment {assignment_item.id} has an invalid member_id {assignment_item.member_id}: {e.detail}")

    return verified_upcoming_assignments


@app.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a ball carrier assignment",
            description="Deletes a ball carrier assignment by its unique ID.")
async def delete_ball_carrier_assignment(assignment_id: str):
    """
    Deletes a ball carrier assignment.

    - **assignment_id**: The unique ID of the assignment to delete.
    """
    # Find the assignment first to ensure it exists before attempting to delete
    existing_assignment = await ball_carrier_assignments_collection.find_one({"id": assignment_id})
    if not existing_assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    result = await ball_carrier_assignments_collection.delete_one({"id": assignment_id})
    if result.deleted_count == 0:
        # This case should ideally not be reached if existing_assignment was found
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found after check.")
    
    return

@app.post("/reminders/send", status_code=status.HTTP_200_OK,
          summary="Send ball carrier reminders",
          description="Simulates sending reminders to the team about current week's ball collectors. In a real system, this would trigger actual notifications.")
async def send_ball_carrier_reminders():
    """
    Simulates sending reminders for the current week's ball collectors.
    This endpoint would typically be called by a scheduled job (e.g., Google Cloud Scheduler).
    It now fetches assignments from MongoDB and attempts to verify member IDs.
    """
    current_collectors = await get_current_ball_collectors() # This now fetches from MongoDB and verifies members

    if not current_collectors:
        print("No ball collectors assigned for the current week. No reminders sent.")
        return {"message": "No ball collectors assigned for the current week. No reminders sent."}

    # Extract member_ids for the reminder message
    # And attempt to fetch actual member names from Team Members Service for a richer reminder
    reminder_details = []
    for assignment in current_collectors:
        try:
            member_info = await check_team_member_exists(assignment.member_id)
            reminder_details.append(f"{member_info.get('name', 'Unknown Member')} (ID: {assignment.member_id})")
        except HTTPException as e:
            print(f"Could not retrieve info for member ID {assignment.member_id} for reminder: {e.detail}")
            reminder_details.append(f"Invalid Member (ID: {assignment.member_id})")

    reminder_message = (
        f"Reminder! This week's ball collectors are: {', '.join(reminder_details)}. "
        "Please ensure all responsibilities are met!"
    )
    print(f"Simulating reminder sent: {reminder_message}")
    return {"message": "Reminder simulation successful", "details": reminder_message}
