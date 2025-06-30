# services/ball_collectors/main.py

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict
import datetime
import uuid

VERSION = "1.0.0"

# Initialize FastAPI app
app = FastAPI(
    title="Ball Collectors Service",
    description="Manages weekly ball carrier assignments and sends reminders."
)

# In-memory database for demonstration purposes
db: Dict[str, dict] = {} # Stores BallCarrierAssignment records

# Pydantic models
class BallCarrierAssignmentBase(BaseModel):
    member_id: str
    assignment_date: datetime.date = Field(..., description="Date for which the assignment is valid (e.g., start of the week).")

class BallCarrierAssignmentCreate(BallCarrierAssignmentBase):
    pass

class BallCarrierAssignmentInDB(BallCarrierAssignmentBase):
    id: str

@app.on_event("startup")
async def startup_event():
    # Pre-populate with some dummy data for testing
    today = datetime.date.today()
    next_week = today + datetime.timedelta(days=7)

    assignment_id_1 = str(uuid.uuid4())
    db[assignment_id_1] = {"id": assignment_id_1, "member_id": "member_id_alice", "assignment_date": today}
    assignment_id_2 = str(uuid.uuid4())
    db[assignment_id_2] = {"id": assignment_id_2, "member_id": "member_id_bob", "assignment_date": next_week}
    print(f"Ball Collectors Service started. Initial assignments: {len(db)}")


@app.get("/")
async def root():
    return {"message": "Ball Collectors Service is running!"}

@app.get("/health", summary="Health Check",
            description="Checks the health of the Ball Collectors Service.")
async def health_check():
    """
    Health check endpoint to verify the service is running.
    """
    return {"status": "ok", "service": "Ball Collectors Service", "version": VERSION}

@app.post("/assignments", response_model=BallCarrierAssignmentInDB, status_code=status.HTTP_201_CREATED,
          summary="Create a new ball carrier assignment",
          description="Assigns a team member as a ball carrier for a specific date (e.g., start of the week).")
async def create_ball_carrier_assignment(assignment: BallCarrierAssignmentCreate):
    """
    Creates a new ball carrier assignment.

    - **member_id**: The ID of the team member assigned.
    - **assignment_date**: The date for which the assignment is valid.
    """ 
    assignment_id = str(uuid.uuid4())
    assignment_data = assignment.model_dump()
    assignment_data["id"] = assignment_id
    db[assignment_id] = assignment_data
    print(f"Created ball carrier assignment for member {assignment_data['member_id']} on {assignment_data['assignment_date']}")
    return BallCarrierAssignmentInDB(**assignment_data)

@app.get("/assignments/current", response_model=List[BallCarrierAssignmentInDB],
          summary="Get current week's ball collectors",
          description="Retrieves ball collectors assigned for the current week.")
async def get_current_ball_collectors():
    """
    Retrieves ball collectors whose assignment date falls within the current week.
    """
    today = datetime.date.today()
    # Assuming "current week" means assignments starting from today up to the next 6 days
    current_week_assignments = [
        BallCarrierAssignmentInDB(**assign)
        for assign in db.values()
        if today <= assign["assignment_date"] < today + datetime.timedelta(days=7)
    ]
    return current_week_assignments

@app.get("/assignments/upcoming", response_model=List[BallCarrierAssignmentInDB],
          summary="Get upcoming ball carrier assignments",
          description="Retrieves all ball carrier assignments scheduled for the future.")
async def get_upcoming_ball_collectors():
    """
    Retrieves all upcoming ball carrier assignments.
    """
    today = datetime.date.today()
    upcoming_assignments = [
        BallCarrierAssignmentInDB(**assign)
        for assign in db.values()
        if assign["assignment_date"] > today
    ]
    # Sort by assignment date
    upcoming_assignments.sort(key=lambda x: x.assignment_date)
    return upcoming_assignments


@app.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a ball carrier assignment",
            description="Deletes a ball carrier assignment by its unique ID.")
async def delete_ball_carrier_assignment(assignment_id: str):
    """
    Deletes a ball carrier assignment.

    - **assignment_id**: The unique ID of the assignment to delete.
    """
    if assignment_id in db:
        del db[assignment_id]
        print(f"Deleted assignment ID: {assignment_id}")
        return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

@app.post("/reminders/send", status_code=status.HTTP_200_OK,
          summary="Send ball carrier reminders",
          description="Simulates sending reminders to the team about current week's ball collectors. In a real system, this would trigger actual notifications.")
async def send_ball_carrier_reminders():
    """
    Simulates sending reminders for the current week's ball collectors.
    This endpoint would typically be called by a scheduled job (e.g., Google Cloud Scheduler).
    """
    current_collectors = await get_current_ball_collectors()
    if not current_collectors:
        print("No ball collectors assigned for the current week. No reminders sent.")
        return {"message": "No ball collectors assigned for the current week. No reminders sent."}

    carrier_member_ids = [carrier.member_id for carrier in current_collectors]
    # In a real application, you would fetch member names from the Team Members Service
    # and then send actual notifications (e.g., email, SMS, push notification)
    # using a service like SendGrid, Twilio, or Google Cloud Pub/Sub with Cloud Functions.

    reminder_message = (
        f"Reminder! This week's ball collectors are: {', '.join(carrier_member_ids)}. "
        "Please ensure all responsibilities are met!"
    )
    print(f"Simulating reminder sent: {reminder_message}")
    return {"message": "Reminder simulation successful", "details": reminder_message}

