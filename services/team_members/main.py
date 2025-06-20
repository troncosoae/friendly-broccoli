from enum import Enum
import os
from typing import List, Dict
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

# Load environment variables
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "team_admin")
COLLECTION = "team_members"

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
    position: Position
    contact_info: str = None

class TeamMemberCreate(TeamMemberBase):
    pass

class TeamMemberUpdate(TeamMemberBase):
    name: str = None
    position: Position = None
    contact_info: str = None

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
    await team_members_collection.insert_one(member_data)
    print(member_data)
    # TODO: Check that it was inserte correctly
    return TeamMemberInDB(**member_data)
    # db[member_id] = member_data
    # print(f"Created member: {member_data['name']} with ID: {member_id}")
    # return TeamMemberInDB(**member_data)

@app.get("/members", response_model=List[TeamMemberInDB],
          summary="Get all team members",
          description="Retrieves a list of all team members.")
async def get_all_team_members():
    """
    Retrieves all team members.
    """
    return [TeamMemberInDB(**member) for member in db.values()]

@app.get("/members/{member_id}", response_model=TeamMemberInDB,
          summary="Get a team member by ID",
          description="Retrieves a specific team member by their unique ID.")
async def get_team_member(member_id: str):
    """
    Retrieves a single team member by their ID.

    - **member_id**: The unique ID of the team member.
    """
    member = db.get(member_id)
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
    if member_id not in db:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")

    current_member = db[member_id]
    updated_data = member_update.model_dump(exclude_unset=True)
    current_member.update(updated_data)
    db[member_id] = current_member
    print(f"Updated member ID: {member_id}")
    return TeamMemberInDB(**current_member)

@app.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a team member",
            description="Deletes a team member from the database by their unique ID.")
async def delete_team_member(member_id: str):
    """
    Deletes a team member.

    - **member_id**: The unique ID of the team member to delete.
    """
    if member_id in db:
        del db[member_id]
        print(f"Deleted member ID: {member_id}")
        return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")

