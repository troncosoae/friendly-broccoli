from datetime import datetime, date
import os
import uuid
from typing import List, Dict, Optional, Set, Union
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import io
import csv

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status, APIRouter, Response
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr, validator
import httpx

# Load environment variables
load_dotenv()

# --- Environment Variable Configuration ---
DEFAULT_MONGODB_URI = "mongodb://localhost:27017"
DEFAULT_DB_NAME = "team_admin"
DEFAULT_TEAM_MEMBERS_SERVICE_URL = "http://team_members_api:80"

MONGODB_URI = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)
DB_NAME = os.getenv("DB_NAME", DEFAULT_DB_NAME)
TEAM_MEMBERS_SERVICE_URL = os.getenv("TEAM_MEMBERS_SERVICE_URL", DEFAULT_TEAM_MEMBERS_SERVICE_URL)

# Email configuration
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_EMAIL_PASSWORD = os.getenv("SENDER_EMAIL_PASSWORD")

# --- Startup Warnings ---
if MONGODB_URI == DEFAULT_MONGODB_URI:
    print(f"Warning: Using default MongoDB URI '{DEFAULT_MONGODB_URI}'.")
if DB_NAME == DEFAULT_DB_NAME:
    print(f"Warning: Using default DB name '{DEFAULT_DB_NAME}'.")
if TEAM_MEMBERS_SERVICE_URL == DEFAULT_TEAM_MEMBERS_SERVICE_URL:
    print(f"Warning: Using default Team Members Service URL '{DEFAULT_TEAM_MEMBERS_SERVICE_URL}'.")
if not SENDER_EMAIL or not SENDER_EMAIL_PASSWORD:
    print("Warning: SENDER_EMAIL or SENDER_EMAIL_PASSWORD not set. Email sending will be disabled.")

CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", None) # Default to '*' if not set
if CORS_ALLOWED_ORIGINS is None:
    print("Warning: CORS_ALLOWED_ORIGINS is set to '*'. This allows all origins, which may not be secure in production.")

# --- Collection Names ---
STAR_SESSIONS_COLLECTION = "star_sessions"
STAR_ASSIGNMENTS_COLLECTION = "star_assignments"

VERSION = "1.0.0"

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Star Tracking Service",
    description="Manages star assignments for team members."
)

origins = CORS_ALLOWED_ORIGINS.split(",") if CORS_ALLOWED_ORIGINS else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allow all origins if '*' or specific origins if set
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allow all headers
)

v1_router = APIRouter(prefix="/v1", tags=["v1"])

# --- Database Client Initialization ---
client = AsyncIOMotorClient(MONGODB_URI)
mg_db = client[DB_NAME]
star_sessions_collection = mg_db[STAR_SESSIONS_COLLECTION]
star_assignments_collection = mg_db[STAR_ASSIGNMENTS_COLLECTION]

# --- Pydantic Models ---

class StarSessionBase(BaseModel):
    team_id: str = Field(..., description="ID of the team for this star session.")
    session_date: date = Field(..., description="Date of the star session (e.g., match or practice).")
    name: str = Field(..., max_length=100, description="Name of the event (e.g., 'Practice Match vs. Opponent').")

class StarSessionCreate(StarSessionBase):
    pass

class StarSessionInDB(StarSessionBase):
    id: str = Field(..., description="Unique ID of the star session.")
    created_at: datetime = Field(..., description="Timestamp of creation.")

class StarAssignmentBase(BaseModel):
    star_session_id: str = Field(..., description="ID of the star session.")
    team_member_id: str = Field(..., description="ID of the team member receiving the star.")
    star_count: float = Field(default=1.0, description="Number of stars assigned (can be positive or negative).")

class StarAssignmentCreate(StarAssignmentBase):
    pass

class StarAssignmentInDB(StarAssignmentBase):
    id: str = Field(..., description="Unique ID of the star assignment.")
    created_at: datetime = Field(..., description="Timestamp of creation.")

class StarAssignmentResponse(BaseModel):
    assignment: StarAssignmentInDB
    warning: Optional[str] = None

class EmailRequest(BaseModel):
    subject: str = Field(..., description="Subject of the email.")

# New models for batch star assignment
class BatchStarAssignmentCreate(BaseModel):
    star_session_id: str = Field(..., description="The ID of the star session to which these assignments belong.")
    assignments: Dict[str, bool] = Field(..., description="A dictionary where keys are team_member_ids and values are booleans indicating if they won a star.")

class BatchStarAssignmentResponse(BaseModel):
    message: str
    created_assignments_count: int
    assignments: List[StarAssignmentInDB]
    warnings: List[str]


# --- Startup Event ---
@app.on_event("startup")
async def startup_event():
    print(f"Star Tracking Service started. Version: {VERSION}")
    print(f"Database: {DB_NAME}, Collections: {STAR_SESSIONS_COLLECTION}, {STAR_ASSIGNMENTS_COLLECTION}")
    print(f"Team Members Service URL: {TEAM_MEMBERS_SERVICE_URL}")

# --- Root and Health Check Endpoints ---
@app.get("/")
async def root():
    return {"message": "Star Tracking Service is running!"}

@app.get("/health", summary="Health Check")
async def health_check():
    return {"status": "ok", "service": "Star Tracking Service", "version": VERSION}

# --- Validation Helpers (External Service Calls) ---
async def _validate_team_exists(team_id: str) -> Dict:
    """Validates team existence by calling the team_members service."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{TEAM_MEMBERS_SERVICE_URL}/v1/teams/{team_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Team with ID '{team_id}' not found.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error validating team: {e.response.text}")
        except httpx.RequestError as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Could not connect to Team Members Service: {e}")

async def _validate_team_member_exists(member_id: str) -> Dict:
    """Validates team member existence by calling the team_members service."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{TEAM_MEMBERS_SERVICE_URL}/v1/members/{member_id}")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Team member with ID '{member_id}' not found.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error validating team member: {e.response.text}")
        except httpx.RequestError as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Could not connect to Team Members Service: {e}")

async def _get_team_members(team_id: str) -> List[Dict]:
    """Gets all members of a team by calling the team_members service."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{TEAM_MEMBERS_SERVICE_URL}/v1/teams/{team_id}/members")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error getting team members: {e.response.text}")
        except httpx.RequestError as e:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Could not connect to Team Members Service: {e}")

# --- Email Sending Helper ---
async def _send_email(to_addrs: List[str], subject: str, body: str):
    """Sends an email using SMTP."""
    if not SENDER_EMAIL or not SENDER_EMAIL_PASSWORD:
        print("Email sending skipped: Email credentials not configured.")
        return False
    
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = ", ".join(to_addrs)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(SENDER_EMAIL, SENDER_EMAIL_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_addrs, msg.as_string())
        print(f"Email successfully sent to {to_addrs}")
        return True
    except Exception as e:
        print(f"An unexpected error occurred while sending email: {e}")
        return False

# --- Star Session CRUD Operations ---
@v1_router.post("/star-sessions", response_model=StarSessionInDB, status_code=status.HTTP_201_CREATED)
async def create_star_session(session: StarSessionCreate):
    """Creates a new star session for a team on a specific date."""
    await _validate_team_exists(session.team_id)
    
    session_id = str(uuid.uuid4())
    session_data = session.model_dump()
    session_data["id"] = session_id
    session_data["created_at"] = datetime.utcnow()
    
    # convert session_date to datetime if needed using noon
    if isinstance(session_data["session_date"], date):
        session_data["session_date"] = datetime.combine(
            session_data["session_date"], datetime.min.time())

    await star_sessions_collection.insert_one(session_data)
    created_session = await star_sessions_collection.find_one({"id": session_id})
    return StarSessionInDB(**created_session)

@v1_router.get("/star-sessions", response_model=List[StarSessionInDB])
async def get_star_sessions(team_id: Optional[str] = None):
    """Retrieves all star sessions, optionally filtered by team_id."""
    query = {}
    if team_id:
        query["team_id"] = team_id
    sessions = await star_sessions_collection.find(query).to_list(length=100)
    return [StarSessionInDB(**s) for s in sessions]

# --- Star Assignment Operations ---
@v1_router.post("/star-assignments", response_model=StarAssignmentResponse, status_code=status.HTTP_201_CREATED)
async def create_star_assignment(assignment: StarAssignmentCreate):
    """Assigns a star to a team member for a specific star session."""
    session = await star_sessions_collection.find_one({"id": assignment.star_session_id})
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Star session not found.")
    
    member = await _validate_team_member_exists(assignment.team_member_id)
    if session["team_id"] not in member.get("team_ids", []):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team member does not belong to the session's team.")
    
    # Check for existing assignments for this player in this session
    existing_assignments_count = await star_assignments_collection.count_documents({
        "star_session_id": assignment.star_session_id,
        "team_member_id": assignment.team_member_id
    })
    
    warning_message = None
    if existing_assignments_count > 0:
        warning_message = "This team member has already been assigned a star in this session. A new assignment has been added."

    assignment_id = str(uuid.uuid4())
    assignment_data = assignment.model_dump()
    assignment_data["id"] = assignment_id
    assignment_data["created_at"] = datetime.utcnow()
    
    await star_assignments_collection.insert_one(assignment_data)
    created_assignment = await star_assignments_collection.find_one({"id": assignment_id})
    
    return StarAssignmentResponse(
        assignment=StarAssignmentInDB(**created_assignment),
        warning=warning_message
    )

@v1_router.post("/star-assignments/batch-create", response_model=BatchStarAssignmentResponse, status_code=status.HTTP_201_CREATED,
            summary="Create star assignments in a batch",
            description="Creates multiple star assignments for a single star session. The input is a dictionary of team member IDs and a boolean indicating if they won a star.")
async def create_batch_star_assignments(batch_request: BatchStarAssignmentCreate):
    """
    Creates multiple star assignments for a single star session in a batch.

    - **star_session_id**: The ID of the star session.
    - **assignments**: A dictionary where keys are team_member_ids and values are booleans.
    """
    # 1. Validate Star Session
    session = await star_sessions_collection.find_one({"id": batch_request.star_session_id})
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Star session not found.")
    
    session_team_id = session["team_id"]

    # 2. Get all team members for validation
    team_members = await _get_team_members(session_team_id)
    team_member_ids_in_team = {member["id"] for member in team_members}

    # 3. Process assignments
    assignments_to_create = []
    warnings = []
    
    # The dictionary keys are unique, so no need to check for duplicates in the payload.
    for member_id, won_star in batch_request.assignments.items():
        if not won_star:
            continue # Skip members who didn't win a star

        # Validate that the member belongs to the team
        if member_id not in team_member_ids_in_team:
            warnings.append(f"Team member with ID '{member_id}' does not belong to the session's team and was skipped.")
            continue

        # Check for existing assignments for this player in this session
        existing_assignments_count = await star_assignments_collection.count_documents({
            "star_session_id": batch_request.star_session_id,
            "team_member_id": member_id
        })
        if existing_assignments_count > 0:
            warnings.append(f"Team member '{member_id}' already had assignments in this session. A new one was added.")

        # Prepare the new assignment document
        assignment_id = str(uuid.uuid4())
        assignment_data = {
            "id": assignment_id,
            "star_session_id": batch_request.star_session_id,
            "team_member_id": member_id,
            "star_count": 1.0, # Defaulting to 1 star as per boolean logic
            "created_at": datetime.utcnow(),
        }
        assignments_to_create.append(assignment_data)

    # 4. Database Insertion
    if not assignments_to_create:
        # This can happen if all `won_star` are false or all members are invalid.
        # Returning a 201 with a message is better than a 400 error.
        return BatchStarAssignmentResponse(
            message="No new assignments were created. This may be because no members were marked as winners or members were not part of the team.",
            created_assignments_count=0,
            assignments=[],
            warnings=warnings
        )

    await star_assignments_collection.insert_many(assignments_to_create)

    # 5. Fetch created assignments and return response
    created_ids = [d["id"] for d in assignments_to_create]
    created_assignments_cursor = star_assignments_collection.find({"id": {"$in": created_ids}})
    created_assignments_list = await created_assignments_cursor.to_list(length=None)

    return BatchStarAssignmentResponse(
        message=f"Successfully created {len(created_assignments_list)} star assignments.",
        created_assignments_count=len(created_assignments_list),
        assignments=[StarAssignmentInDB(**a) for a in created_assignments_list],
        warnings=warnings
    )

@v1_router.get("/star-assignments", response_model=List[StarAssignmentInDB])
async def get_star_assignments(session_id: Optional[str] = None, team_member_id: Optional[str] = None):
    """Retrieves all star assignments, optionally filtered by session or team member."""
    query = {}
    if session_id:
        query["star_session_id"] = session_id
    if team_member_id:
        query["team_member_id"] = team_member_id
    assignments = await star_assignments_collection.find(query).to_list(length=100)
    return [StarAssignmentInDB(**a) for a in assignments]

# --- Email and CSV Endpoints ---
@v1_router.post("/star-sessions/{session_id}/send-email", status_code=status.HTTP_200_OK)
async def send_star_session_email(session_id: str, email_request: EmailRequest):
    """Sends an email to all team members detailing who won stars in a session."""
    session = await star_sessions_collection.find_one({"id": session_id})
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Star session not found.")
    
    team_members = await _get_team_members(session["team_id"])
    if not team_members:
        return {"message": "No team members found for this team. No emails sent."}
    
    assignments = await star_assignments_collection.find({"star_session_id": session_id}).to_list(length=None)
    if not assignments:
        return {"message": "No star assignments found for this session. No emails sent."}

    # Aggregate stars per member
    star_winners: Dict[str, float] = {}
    for a in assignments:
        member_id = a["team_member_id"]
        star_winners[member_id] = star_winners.get(member_id, 0) + a["star_count"]

    # Prepare email content
    member_details = {m["id"]: m for m in team_members}
    
    winner_list_html = "<ul>"
    for member_id, count in star_winners.items():
        name = member_details.get(member_id, {}).get("name", "Unknown Member")
        winner_list_html += f"<li>{name}: {count} star(s)</li>"
    winner_list_html += "</ul>"

    email_body = f"""
    <html>
    <body>
        <h2>Star Awards for {session['name']} on {session['session_date']}</h2>
        <p>Hi Team,</p>
        <p>Here are the star assignments for the recent event:</p>
        {winner_list_html}
        <p>Congratulations to the winners!</p>
    </body>
    </html>
    """
    
    recipient_emails = [m["email"] for m in team_members if "email" in m]
    if not recipient_emails:
        return {"message": "No valid email addresses found for team members."}

    email_sent = await _send_email(recipient_emails, email_request.subject, email_body)
    if email_sent:
        return {"message": f"Email successfully sent to {len(recipient_emails)} team members."}
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to send email.")

@v1_router.get("/teams/{team_id}/stars-report/download", summary="Download Star Counts as CSV")
async def download_stars_csv(team_id: str, start_date: date, end_date: date):
    """Downloads a CSV report of star counts for a team over a period."""
    await _validate_team_exists(team_id)
    team_members = await _get_team_members(team_id)

    start_date = datetime.combine(start_date, datetime.min.time())
    end_date = datetime.combine(end_date, datetime.max.time())

    # Find all sessions for the team within the date range
    sessions = await star_sessions_collection.find({
        "team_id": team_id,
        "session_date": {"$gte": start_date, "$lte": end_date}
    }).to_list(length=None)
    
    if not sessions:
        return Response("No star sessions found for the given team and date range.", media_type="text/plain")

    session_ids = [s["id"] for s in sessions]
    session_map = {s["id"]: f"{s['name']} ({s['session_date']})" for s in sessions}

    # Find all assignments for those sessions
    assignments = await star_assignments_collection.find({"star_session_id": {"$in": session_ids}}).to_list(length=None)

    # Structure data for CSV
    # Rows: team members, Columns: star sessions
    report_data: Dict[str, Dict[str, float]] = {member["id"]: {} for member in team_members}
    for a in assignments:
        member_id = a["team_member_id"]
        session_id = a["star_session_id"]
        if member_id in report_data:
            report_data[member_id][session_id] = report_data[member_id].get(session_id, 0) + a["star_count"]

    # Create CSV in-memory
    output = io.StringIO()
    # Sort sessions by date for column order
    sorted_sessions = sorted(sessions, key=lambda s: s['session_date'])
    sorted_session_ids = [s['id'] for s in sorted_sessions]
    
    header = ["Team Member"] + [session_map[sid] for sid in sorted_session_ids] + ["Total Stars"]
    writer = csv.writer(output)
    writer.writerow(header)
    
    for member in team_members:
        row = [member["name"]]
        for session_id in sorted_session_ids:
            row.append(report_data[member["id"]].get(session_id, 0))
        row.append(sum(row[1:]))
        writer.writerow(row)

    output.seek(0)
    
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=stars_report_{team_id}_{start_date}_to_{end_date}.csv"}
    )

app.include_router(v1_router)
