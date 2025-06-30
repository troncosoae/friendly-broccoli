from datetime import datetime
from enum import Enum
import os
from typing import List, Dict
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr

# Load environment variables
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "team_admin")
COLLECTION = "team_members"

VERSION = "1.0.0"

# Initialize FastAPI app
app = FastAPI(
    title="Team Members Service",
    description="Manages team member information."
)

client = AsyncIOMotorClient(MONGODB_URI)
mg_db = client[DB_NAME]
team_members_collection = mg_db[COLLECTION]

# In-memory database for demonstration purposes
# In a real application, replace this with a persistent database (e.g., PostgreSQL, MongoDB, Firestore)
db: Dict[str, dict] = {}

class Position(str, Enum):
    FORWARD = "Forward"
    DEFENDER = "Defender"
    MIDFIELDER = "Midfielder"
    GOALKEEPER = "Goalkeeper"

    def __str__(self):
        return self.value
    def __repr__(self):
        return self.value
    def __eq__(self, other):
        if isinstance(other, str):
            return self.value == other
        return super().__eq__(other)

# Pydantic models for request and response validation
class TeamMemberBase(BaseModel):
    name: str
    email: EmailStr # Unique
    phone: str # Unique
    date_of_birth: datetime
    date_joined: datetime

class TeamMemberCreate(TeamMemberBase):
    pass

class TeamMemberUpdate(TeamMemberBase):
    name: str
    email: EmailStr # Unique
    phone: str # Unique
    date_of_birth: datetime
    date_joined: datetime

class TeamMemberInDB(TeamMemberBase):
    id: str

@app.on_event("startup")
async def startup_event():
    # Pre-populate with some dummy data for testing
    member_id_1 = str(uuid.uuid4())
    db[member_id_1] = {"id": member_id_1, "name": "Alice Johnson", "position": "Forward", "contact_info": "alice@example.com"}
    member_id_2 = str(uuid.uuid4())
    db[member_id_2] = {"id": member_id_2, "name": "Bob Smith", "position": "Defender", "contact_info": "bob@example.com"}
    print(f"Team Members Service started. Initial members: {len(db)}")
    print(f"Connecing to database at {MONGODB_URI} with DB name {DB_NAME} and collection {COLLECTION}")


@app.get("/")
async def root():
    return {"message": "Team Members Service is running!"}

@app.get("/health", summary="Health Check",
          description="Checks the health of the Team Members Service.")
async def health_check():
    """
    Health check endpoint to verify the service is running.
    """
    return {"status": "ok", "service": "Team Members Service", "version": VERSION}

@app.post("/members", response_model=TeamMemberInDB, status_code=status.HTTP_201_CREATED,
          summary="Create a new team member",
          description="Adds a new team member to the database with a unique ID.")
async def create_team_member(member: TeamMemberCreate):
    """
    Creates a new team member.

    - **name**: Name of the team member.
    - **position**: Player position (e.g., "Forward", "Defender").
    - **contact_info**: Contact details (optional).
    """
    member_id = str(uuid.uuid4())
    member_data = member.model_dump()
    member_data["id"] = member_id

    print(member_data)

    # Make sure the phone and email haven't yet been inserted
    equal_phone_member = await team_members_collection.find_one({"phone": member_data["phone"]})
    print(equal_phone_member, flush=True)
    if equal_phone_member is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A team member with this phone already exists.")
    equal_email_member = await team_members_collection.find_one({"email": member_data["email"]})
    print(equal_email_member, flush=True)
    if equal_email_member is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A team member with this email already exists.")

    await team_members_collection.insert_one(member_data)
    member = await team_members_collection.find_one({"id": member_id})
    return TeamMemberInDB(**member)

@app.get("/members", response_model=List[TeamMemberInDB],
          summary="Get all team members",
          description="Retrieves a list of all team members.")
async def get_all_team_members():
    """
    Retrieves all team members.
    """
    members = await team_members_collection.find().to_list(length=None)
    if len(members) > 100:
        members = members[:100]  # Limit to 100 members for performance
    return [TeamMemberInDB(**member) for member in members]

@app.get("/members/{member_id}", response_model=TeamMemberInDB,
          summary="Get a team member by ID",
          description="Retrieves a specific team member by their unique ID.")
async def get_team_member(member_id: str):
    """
    Retrieves a single team member by their ID.

    - **member_id**: The unique ID of the team member.
    """
    member = await team_members_collection.find_one({"id": member_id})
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")
    return TeamMemberInDB(**member)

@app.put("/members/{member_id}", response_model=TeamMemberInDB,
          summary="Update a team member",
          description="Updates an existing team member's information. Only provided fields will be updated.")
async def update_team_member(member_id: str, member_update: TeamMemberUpdate):
    """
    Updates an existing team member.

    - **member_id**: The unique ID of the team member to update.
    - **name**: New name (optional).
    - **position**: New position (optional).
    - **contact_info**: New contact details (optional).
    """
    member = await team_members_collection.find_one({"id": member_id})
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")
    
    # Make sure the phone and email haven't yet been inserted
    equal_phone_member = await team_members_collection.find_one({
        "phone": member["phone"],
        "id": {"ne": member_id}})
    print(equal_phone_member, flush=True)
    if equal_phone_member is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A team member with this phone already exists.")
    equal_email_member = await team_members_collection.find_one({
        "email": member["email"],
        "id": {"ne": member_id}})
    print(equal_email_member, flush=True)
    if equal_email_member is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A team member with this email already exists.")
    
    # Update the member data with the provided fields
    member_data = member_update.model_dump(exclude_unset=True)
    member_data["id"] = member_id  # Ensure the ID remains the same
    member = await team_members_collection.find_one_and_update(
        {"id": member_id},
        {"$set": member_data},
        return_document=True
    )

    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")
    print(f"Updated member ID: {member_id}")
    return TeamMemberInDB(**member)

@app.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a team member",
            description="Deletes a team member from the database by their unique ID.")
async def delete_team_member(member_id: str):
    """
    Deletes a team member.

    - **member_id**: The unique ID of the team member to delete.
    """
    member = await team_members_collection.find_one({"id": member_id})
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")
    # Delete the member from the database
    result = await team_members_collection.delete_one({"id": member_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")
    return TeamMemberInDB(**member)
