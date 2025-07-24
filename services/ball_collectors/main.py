from datetime import datetime, timedelta, date
import os
import uuid
from typing import List, Dict, Optional, Set
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import itertools
import random

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status, APIRouter
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ValidationError
import httpx # Import httpx for making asynchronous HTTP requests

# Load environment variables
load_dotenv()

DEFAULT_MONGODB_URI = "mongodb://localhost:27017"
DEFAULT_DB_NAME = "team_admin"
DEFAULT_TEAM_MEMBERS_SERVICE_URL = "http://team_members_api:80"

MONGODB_URI = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)
DB_NAME = os.getenv("DB_NAME", DEFAULT_DB_NAME)
TEAM_MEMBERS_SERVICE_URL = os.getenv(
    "TEAM_MEMBERS_SERVICE_URL", DEFAULT_TEAM_MEMBERS_SERVICE_URL) # URL of your main.py service

# Email configuration
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_EMAIL_PASSWORD = os.getenv("SENDER_EMAIL_PASSWORD") # This should be an App Password for Gmail
print(f"Sender email: {SENDER_EMAIL}")
print(f"Sender email password: {SENDER_EMAIL_PASSWORD}")

if (MONGODB_URI == DEFAULT_MONGODB_URI):
    print(f"Warning: Using default MongoDB URI 'MONGODB_URI'. Ensure this is correct for your environment.")
if (DB_NAME == DEFAULT_DB_NAME):
    print(f"Warning: Using default DB name '{DB_NAME}'. Ensure this is correct for your environment.")
if (TEAM_MEMBERS_SERVICE_URL == DEFAULT_TEAM_MEMBERS_SERVICE_URL):
    print(f"Warning: Using default Team Members Service URL '{TEAM_MEMBERS_SERVICE_URL}'. Ensure this is correct for your environment.")
if not SENDER_EMAIL:
    print("Warning: SENDER_EMAIL environment variable is not set. Email sending will not work.")
if not SENDER_EMAIL_PASSWORD:
    print("Warning: SENDER_EMAIL_PASSWORD environment variable is not set. Email sending will not work.")


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

# New Pydantic model for email request (body is now dynamically generated)
class UpcomingBallCollectionEmailRequest(BaseModel):
    subject: str = Field(..., description="Subject of the email.")

# New Pydantic models for batch creation
class BatchBallCollectionCreate(BaseModel):
    team_id: str = Field(..., description="ID of the team to create responsibilities for.")
    members_per_week: int = Field(..., gt=0, description="Number of members to assign per week.")
    start_date: date = Field(..., description="The start date for creating assignments (inclusive).")
    end_date: date = Field(..., description="The end date for creating assignments (inclusive).")

class BatchBallCollectionResponse(BaseModel):
    message: str
    created_assignments_count: int
    assignments: List[BallCollectionInDB]
    email_status: str

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
    Returns the team data if found.
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
    Returns the member data if found.
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

async def _get_team_members(team_id: str) -> List[Dict]:
    """
    Helper to get all team members for a given team ID.
    This function now calls the external Team Members Service API.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{TEAM_MEMBERS_SERVICE_URL}/v1/teams/{team_id}/members")
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            return response.json() # Return the list of member data if found
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Team with ID '{team_id}' not found via external service."
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error getting team members for team with ID '{team_id}': {e.response.text}"
                )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not connect to Team Members Service to get team members: {e}"
            )

def _validate_dates(start_date: datetime, end_date: datetime):
    """Helper to validate that start_date is before end_date."""
    if start_date >= end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End date must be after start date."
        )

# --- Email Sending Helper ---
async def _send_email(to_addrs: List[str], cc_addrs: List[str], subject: str, body: str):
    """
    Sends an email using SMTP.
    Requires SENDER_EMAIL and SENDER_EMAIL_PASSWORD environment variables to be set.
    For Gmail, SENDER_EMAIL_PASSWORD should be an App Password.
    """
    if not SENDER_EMAIL or not SENDER_EMAIL_PASSWORD:
        print("Email sending skipped: SENDER_EMAIL or SENDER_EMAIL_PASSWORD not configured.")
        return False

    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = ", ".join(to_addrs)
    if cc_addrs:
        msg['Cc'] = ", ".join(cc_addrs)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        # For Gmail, use 'smtp.gmail.com' and port 587 with TLS
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server: # Using 465 for SSL directly
            # server.starttls() # Not needed for SMTP_SSL
            server.login(SENDER_EMAIL, SENDER_EMAIL_PASSWORD)
            recipients = to_addrs + cc_addrs
            server.sendmail(SENDER_EMAIL, recipients, msg.as_string())
        print(f"Email successfully sent to {to_addrs} (CC: {cc_addrs})")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP Authentication Error: {e}. Check SENDER_EMAIL and SENDER_EMAIL_PASSWORD (App Password).")
        return False
    except smtplib.SMTPConnectError as e:
        print(f"SMTP Connection Error: {e}. Could not connect to the SMTP server.")
        return False
    except Exception as e:
        print(f"An unexpected error occurred while sending email: {e}")
        return False

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

@v1_router.post("/ball-collections/batch-create", response_model=BatchBallCollectionResponse, status_code=status.HTTP_201_CREATED,
            summary="Create a batch of ball collection responsibilities for a team",
            description="Generates weekly ball collection assignments for a team over a specified period and notifies all team members via email.")
async def create_batch_ball_collections(batch_request: BatchBallCollectionCreate):
    """
    Creates ball collection responsibilities in weekly batches for a team.

    - **team_id**: The ID of the team for which to create assignments.
    - **members_per_week**: The number of members assigned per week.
    - **start_date**: The start date for the assignment period.
    - **end_date**: The end date for the assignment period.
    """
    # 1. Validate input
    team_id = batch_request.team_id
    team_data = await _validate_team_exists(team_id)
    team_name = team_data.get("name", f"Team {team_id}")

    if batch_request.start_date >= batch_request.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End date must be after start date."
        )

    # 2. Fetch team members
    team_members = await _get_team_members(team_id)
    if not team_members:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No members found for team with ID '{team_id}'. Cannot create assignments."
        )

    # 3. Rotation and Assignment Logic
    new_assignments_data = []
    # Suffle the members to ensure random assignment each time
    random.shuffle(team_members)  # Shuffle to ensure random assignment each time
    # Use itertools.cycle for continuous, easy rotation of members
    member_cycler = itertools.cycle(team_members)
    
    current_date = batch_request.start_date
    while current_date <= batch_request.end_date:
        # Define the week's start and end datetimes
        week_start_dt = datetime.combine(current_date, datetime.min.time())
        # The responsibility ends at the end of the 6th day (start of 7th day)
        week_end_dt = week_start_dt + timedelta(days=7)

        # Assign members for this week
        for _ in range(batch_request.members_per_week):
            responsible_member = next(member_cycler)
            member_id = responsible_member["id"]
            
            assignment_id = str(uuid.uuid4())
            assignment_data = {
                "id": assignment_id,
                "responsible_id": member_id,
                "team_id": team_id,
                "start_date": week_start_dt,
                "end_date": week_end_dt,
                "assigned_date": datetime.utcnow(),
                "created_at": datetime.utcnow(),
                "updated_at": None,
            }
            new_assignments_data.append(assignment_data)

        # Move to the next week
        current_date += timedelta(weeks=1)

    if not new_assignments_data:
        return BatchBallCollectionResponse(
            message="No assignments were needed for the given date range.",
            created_assignments_count=0,
            assignments=[],
            email_status="not_sent"
        )

    # 4. Database Insertion
    await ball_collectors_collection.insert_many(new_assignments_data)
    
    # Fetch the created assignments to return them in the response
    created_ids = [d["id"] for d in new_assignments_data]
    created_assignments_cursor = ball_collectors_collection.find({"id": {"$in": created_ids}})
    created_assignments_list = await created_assignments_cursor.to_list(length=None)
    
    # 5. Email Logic
    all_member_emails = [m["email"] for m in team_members if m.get("email")]
    member_details_map = {m["id"]: m for m in team_members}

    # Prepare email body with a summary of assignments
    email_body = f"Hi Team {team_name},\n\nNew ball collection responsibilities have been assigned as follows:\n\n"
    
    # Group assignments by week for a clean email format
    assignments_by_week = {}
    for assignment in created_assignments_list:
        week_start_str = assignment['start_date'].strftime('%Y-%m-%d')
        if week_start_str not in assignments_by_week:
            assignments_by_week[week_start_str] = []
        
        responsible_member_name = member_details_map.get(assignment['responsible_id'], {}).get('name', 'Unknown Member')
        assignments_by_week[week_start_str].append(responsible_member_name)

    for week_start_str, names in sorted(assignments_by_week.items()):
        email_body += f"Week of {week_start_str}:\n"
        for name in names:
            email_body += f"- {name}\n"
        email_body += "\n"

    email_body += "Thank you,\nTeam Admin"

    # Send the email
    email_status = "not_sent"
    if all_member_emails:
        email_sent = await _send_email(
            to_addrs=all_member_emails,
            cc_addrs=[], # Sending to all, so no CC needed
            subject=f"New Ball Collection Schedule for {team_name}",
            body=email_body
        )
        email_status = "sent_successfully" if email_sent else "send_failed"

    return BatchBallCollectionResponse(
        message=f"Successfully created {len(created_assignments_list)} new ball collection assignments for {team_name}.",
        created_assignments_count=len(created_assignments_list),
        assignments=[BallCollectionInDB(**a) for a in created_assignments_list],
        email_status=email_status
    )

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

@v1_router.post("/ball-collections/send-upcoming-emails", status_code=status.HTTP_200_OK,
            summary="Send emails to teams with upcoming ball collection duties",
            description="Identifies teams with members responsible for ball collection within the next 7 days and sends a single email per team.")
async def send_upcoming_ball_collection_emails(
    email_request: UpcomingBallCollectionEmailRequest,
    team_id: Optional[str] = None # Added team_id as an optional query parameter
):
    """
    Sends a single email per team to all team members who have ball collection responsibilities
    starting within the next 7 days. The email lists the responsible members for that team,
    with other team members CC'd.

    - **subject**: The subject line of the email.
    - **team_id**: Optional. If provided, emails will only be sent for this specific team.
    """
    now = datetime.utcnow()
    seven_days_from_now = now + timedelta(days=7)

    # Find assignments where the start_date is within the next 7 days
    # and the end_date has not passed yet.
    query_filter = {
        "start_date": {"$lte": seven_days_from_now},
        "end_date": {"$gte": now}
    }

    if team_id:
        # If a specific team_id is provided, validate it and add to the filter
        await _validate_team_exists(team_id)
        query_filter["team_id"] = team_id

    upcoming_assignments = await ball_collectors_collection.find(query_filter).to_list(length=None)

    if not upcoming_assignments:
        return {"message": "No upcoming ball collection assignments found in the next 7 days. No emails sent."}

    # Group responsible members by team
    team_responsible_members: Dict[str, Set[str]] = {}
    for assignment in upcoming_assignments:
        current_team_id = assignment["team_id"]
        responsible_id = assignment["responsible_id"]
        if current_team_id not in team_responsible_members:
            team_responsible_members[current_team_id] = set()
        team_responsible_members[current_team_id].add(responsible_id)

    sent_emails_count = 0
    failed_emails: List[Dict] = []
    
    async with httpx.AsyncClient() as client:
        for current_team_id, responsible_member_ids in team_responsible_members.items():
            try:
                # 1. Fetch team details to get team name and all member IDs
                team_data = await _validate_team_exists(current_team_id) # This helper now returns team data
                
                if not team_data:
                    failed_emails.append({"team_id": current_team_id, "reason": "Team data not found."})
                    continue
                
                team_name = team_data.get("name", f"Team {current_team_id}")
                
                # Fetch all members of the team using the new _get_team_members helper
                team_members_list = await _get_team_members(current_team_id)
                if not team_members_list:
                    failed_emails.append({"team_id": current_team_id, "reason": "No team members found for this team."})
                    continue
                
                all_team_member_ids = {member["id"] for member in team_members_list}

                # 2. Fetch details for all relevant members (responsible and all team members)
                all_relevant_member_ids = responsible_member_ids.union(all_team_member_ids)
                member_details: Dict[str, Dict] = {}
                for member_id in all_relevant_member_ids:
                    try:
                        member_data = await _validate_team_member_exists(member_id) # This helper now returns member data
                        member_details[member_id] = member_data
                    except HTTPException as e:
                        print(f"Warning: Could not fetch details for member {member_id}: {e.detail}")
                        failed_emails.append({"team_id": current_team_id, "member_id": member_id, "reason": f"Could not fetch member details: {e.detail}"})
                    except Exception as e:
                        print(f"Warning: Unexpected error fetching details for member {member_id}: {e}")
                        failed_emails.append({"team_id": current_team_id, "member_id": member_id, "reason": f"Unexpected error fetching member details: {e}"})


                # 3. Determine 'To' and 'CC' recipients
                to_emails: List[str] = []
                cc_emails: List[str] = []
                responsible_names: List[str] = []

                for member_id in responsible_member_ids:
                    member_info = member_details.get(member_id)
                    if member_info and member_info.get("email"):
                        to_emails.append(member_info["email"])
                        responsible_names.append(member_info.get("name", member_id))
                    else:
                        failed_emails.append({"team_id": current_team_id, "member_id": member_id, "reason": "Responsible member email not found."})

                for member_id in all_team_member_ids:
                    if member_id not in responsible_member_ids: # Only CC members who are not responsible
                        member_info = member_details.get(member_id)
                        if member_info and member_info.get("email"):
                            cc_emails.append(member_info["email"])
                        else:
                            failed_emails.append({"team_id": current_team_id, "member_id": member_id, "reason": "CC member email not found."})

                # 4. Construct email body
                if not responsible_names:
                    # If no responsible members could be found with emails, skip sending for this team
                    failed_emails.append({"team_id": current_team_id, "reason": "No responsible members with valid emails found for this team."})
                    continue

                responsible_list_str = "\n- " + "\n- ".join(responsible_names)
                email_body = (
                    f"Hi Team,\n\n"
                    f"For the team {team_name}, the members who are responsible for ball collection within the next 7 days are:{responsible_list_str}\n\n"
                    f"Please support them as needed!"
                )

                # 5. Send email
                if to_emails: # Only attempt to send if there are 'To' recipients
                    email_sent = await _send_email(to_emails, cc_emails, email_request.subject, email_body)
                    if email_sent:
                        sent_emails_count += 1
                    else:
                        failed_emails.append({"team_id": current_team_id, "reason": "Failed to send email via SMTP."})
                else:
                    failed_emails.append({"team_id": current_team_id, "reason": "No valid 'To' recipients for this team's email."})

            except HTTPException as e:
                failed_emails.append({
                    "team_id": current_team_id,
                    "reason": f"Error processing team {current_team_id}: {e.detail}"
                })
            except httpx.RequestError as e:
                failed_emails.append({
                    "team_id": current_team_id,
                    "reason": f"Could not connect to Team Members Service for team {current_team_id}: {e}"
                })
            except Exception as e:
                failed_emails.append({
                    "team_id": current_team_id,
                    "reason": f"An unexpected error occurred for team {current_team_id}: {e}"
                })

    response_message = f"Successfully sent emails for {sent_emails_count} teams."
    if failed_emails:
        response_message += f" Failed to process or send emails for some members/teams."
        return {
            "message": response_message,
            "sent_team_emails_count": sent_emails_count,
            "failed_details": failed_emails
        }
    
    return {
        "message": response_message,
        "sent_team_emails_count": sent_emails_count,
        "failed_details": []
    }


app.include_router(v1_router)
