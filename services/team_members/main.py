from datetime import datetime
from enum import Enum
import os
from typing import List, Dict, Optional, Set
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status, Query, APIRouter
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field, BeforeValidator
from typing_extensions import Annotated


# Load environment variables
load_dotenv()

DEFAULT_MONGODB_URI = "mongodb://localhost:27017"
DEFAULT_DB_NAME = "team_admin"

MONGODB_URI = os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI)
DB_NAME = os.getenv("DB_NAME", DEFAULT_DB_NAME)

if (MONGODB_URI == DEFAULT_MONGODB_URI):
    print(f"Warning: Using default MongoDB URI 'MONGODB_URI'. Ensure this is correct for your environment.")
if (DB_NAME == DEFAULT_DB_NAME):
    print(f"Warning: Using default DB name '{DB_NAME}'. Ensure this is correct for your environment.")

TEAM_COLLECTION = "teams"
TEAM_MEMBERS_COLLECTION = "team_members"
COACH_COLLECTION = "coaches"
TEAM_COACH_ROLES_COLLECTION = "team_coach_roles" # New collection for coach-team relationships

VERSION = "1.0.0"

# Initialize FastAPI app
app = FastAPI(
    title="Team, Team Members, and Coaches Service",
    description="Manages team, team member, and coach information."
)

v1_router = APIRouter(prefix="/v1", tags=["v1"])

client = AsyncIOMotorClient(MONGODB_URI)
mg_db = client[DB_NAME]
teams_collection = mg_db[TEAM_COLLECTION]
team_members_collection = mg_db[TEAM_MEMBERS_COLLECTION]
coaches_collection = mg_db[COACH_COLLECTION]
team_coach_roles_collection = mg_db[TEAM_COACH_ROLES_COLLECTION] # Initialize team_coach_roles collection

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

class Role(str, Enum):
    HEAD = "HEAD"
    FITNESS = "FITNESS"
    COACH = "COACH"

    def __str__(self):
        return self.value
    def __repr__(self):
        return self.value
    def __eq__(self, other):
        if isinstance(other, str):
            return self.value == other
        return super().__eq__(other)

# Helper function to ensure team_ids is always a list, even if a single string is provided
def ensure_list(v: any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        # Ensure all elements in the list are strings
        if not all(isinstance(item, str) for item in v):
            raise ValueError("All items in list must be strings")
        return v
    raise ValueError("Input must be a string or a list of strings")

# Pydantic models for Team
class TeamBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Name of the team.")
    captain_id: Optional[str] = Field(None, description="ID of the team member who is the captain of this team.")

class TeamCreate(TeamBase):
    pass

class TeamUpdate(TeamBase):
    name: str = Field(None, min_length=1, max_length=100, description="New name of the team.")
    captain_id: Optional[str] = Field(None, description="New ID of the team member who is the captain of this team. Set to null to remove captain.")

class TeamInDB(TeamBase):
    id: str = Field(..., description="Unique ID of the team.")
    created_at: datetime = Field(..., description="Timestamp when the team was created.")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when the team was last updated.")

# Pydantic models for Coach
class CoachBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Name of the coach.")
    email: EmailStr = Field(..., description="Unique email address of the coach.")
    phone: str = Field(..., min_length=5, max_length=20, description="Unique phone number of the coach.")

class CoachCreate(CoachBase):
    pass

class CoachUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="New name of the coach.")
    email: Optional[EmailStr] = Field(None, description="New unique email address of the coach.")
    phone: Optional[str] = Field(None, min_length=5, max_length=20, description="New unique phone number of the coach.")

class CoachInDB(CoachBase):
    id: str = Field(..., description="Unique ID of the coach.")
    created_at: datetime = Field(..., description="Timestamp when the coach was created.")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when the coach was last updated.")

# Pydantic models for TeamCoachRole (new collection)
class TeamCoachRoleBase(BaseModel):
    coach_id: str = Field(..., description="ID of the coach.")
    team_id: str = Field(..., description="ID of the team.")
    role: Role = Field(..., description="Role of the coach within this team.")

class TeamCoachRoleCreate(TeamCoachRoleBase):
    pass

class TeamCoachRoleUpdate(BaseModel):
    role: Optional[Role] = Field(None, description="New role of the coach within this team.")

class TeamCoachRoleInDB(TeamCoachRoleBase):
    id: str = Field(..., description="Unique ID of the coach-team role.")
    created_at: datetime = Field(..., description="Timestamp when the role was assigned.")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when the role was last updated.")


# Pydantic models for Team Member
class TeamMemberBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Name of the team member.")
    email: EmailStr = Field(..., description="Unique email address of the team member.")
    phone: str = Field(..., min_length=5, max_length=20, description="Unique phone number of the team member.")
    date_of_birth: datetime = Field(..., description="Date of birth of the team member.")
    date_joined: datetime = Field(..., description="Date when the team member joined.")
    team_ids: Annotated[List[str], BeforeValidator(ensure_list)] = Field(default_factory=list, description="List of IDs of the teams the member belongs to.")

class TeamMemberCreate(TeamMemberBase):
    pass

class TeamMemberUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="New name of the team member.")
    email: Optional[EmailStr] = Field(None, description="New unique email address of the team member.")
    phone: Optional[str] = Field(None, min_length=5, max_length=20, description="New unique phone number of the team member.")
    date_of_birth: Optional[datetime] = Field(None, description="New date of birth of the team member.")
    date_joined: Optional[datetime] = Field(None, description="New date when the team member joined.")
    team_ids: Optional[Annotated[List[str], BeforeValidator(ensure_list)]] = Field(None, description="New list of IDs of the teams the member belongs to.")

class TeamMemberInDB(TeamMemberBase):
    id: str = Field(..., description="Unique ID of the team member.")
    created_at: datetime = Field(..., description="Timestamp when the member was created.")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when the member was last updated.")


@app.on_event("startup")
async def startup_event():
    print(f"Team, Team Members, and Coaches Service started. Connecting to database at {MONGODB_URI} with DB name {DB_NAME}")
    print(f"Collections: {TEAM_COLLECTION}, {TEAM_MEMBERS_COLLECTION}, {COACH_COLLECTION}, {TEAM_COACH_ROLES_COLLECTION}")


@app.get("/")
async def root():
    return {"message": "Team, Team Members, and Coaches Service is running!"}

@app.get("/health", summary="Health Check",
          description="Checks the health of the Team, Team Members, and Coaches Service.")
async def health_check():
    """
    Health check endpoint to verify the service is running.
    """
    return {"status": "ok", "service": "Team, Team Members, and Coaches Service", "version": VERSION}

# --- Shared Validation Helpers ---

async def _validate_email_phone_uniqueness(
    collection: AsyncIOMotorClient,
    email: EmailStr,
    phone: str,
    entity_id: Optional[str] = None
):
    """Helper to validate unique email and phone for a given collection (members or coaches)."""
    query_email = {"email": email}
    query_phone = {"phone": phone}

    if entity_id:
        query_email["id"] = {"$ne": entity_id}
        query_phone["id"] = {"$ne": entity_id}

    equal_email_entity = await collection.find_one(query_email)
    if equal_email_entity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An entity with email '{email}' already exists in this collection."
        )

    equal_phone_entity = await collection.find_one(query_phone)
    if equal_phone_entity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An entity with phone '{phone}' already exists in this collection."
        )

async def _validate_team_exists(team_id: str):
    """Helper to validate if a team exists."""
    team = await teams_collection.find_one({"id": team_id})
    if not team:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Team with ID '{team_id}' not found."
        )
    return team

async def _validate_team_ids_exist(team_ids: List[str]):
    """Helper to validate if all team IDs in a list exist."""
    if not team_ids:
        return # No team_ids to validate

    # Get unique team_ids to avoid redundant lookups
    unique_team_ids = list(set(team_ids))

    for team_id in unique_team_ids:
        await _validate_team_exists(team_id)

async def _validate_team_member_exists(member_id: str):
    """Helper to validate if a team member exists."""
    member = await team_members_collection.find_one({"id": member_id})
    if not member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Team member with ID '{member_id}' not found."
        )
    return member

async def _validate_coach_exists(coach_id: str):
    """Helper to validate if a coach exists."""
    coach = await coaches_collection.find_one({"id": coach_id})
    if not coach:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Coach with ID '{coach_id}' not found."
        )
    return coach

# --- Team CRUD Operations ---

@v1_router.post("/teams", response_model=TeamInDB, status_code=status.HTTP_201_CREATED,
          summary="Create a new team",
          description="Adds a new team to the database with a unique ID.")
async def create_team(team: TeamCreate):
    """
    Creates a new team.

    - **name**: Name of the team.
    - **captain_id**: Optional ID of the team member who is the captain.
    """
    existing_team = await teams_collection.find_one({"name": team.name})
    if existing_team:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A team with the name '{team.name}' already exists."
        )

    if team.captain_id:
        captain = await _validate_team_member_exists(team.captain_id)
        # Ensure the captain belongs to this team (even before it's officially created, for validation)
        # This check is more complex now as the team_id for this new team doesn't exist yet.
        # For simplicity, we'll assume the captain can be assigned and the member's team_ids will be updated separately.
        # A more robust solution might involve a transaction or a deferred validation.
        # For now, we'll just check if the captain exists.

    team_id = str(uuid.uuid4())
    team_data = team.model_dump()
    team_data["id"] = team_id
    team_data["created_at"] = datetime.utcnow()
    team_data["updated_at"] = None

    await teams_collection.insert_one(team_data)

    # If a captain is assigned, update the team member's team_ids to include this new team
    if team.captain_id:
        await team_members_collection.update_one(
            {"id": team.captain_id},
            {"$addToSet": {"team_ids": team_id}} # Add team_id if not already present
        )

    created_team = await teams_collection.find_one({"id": team_id})
    return TeamInDB(**created_team)

@v1_router.get("/teams", response_model=List[TeamInDB],
          summary="Get all teams",
          description="Retrieves a list of all teams.")
async def get_all_teams():
    """
    Retrieves all teams.
    """
    teams = await teams_collection.find().to_list(length=None)
    # Limit to 100 teams for performance, can be paginated in a real app
    if len(teams) > 100:
        teams = teams[:100]
    return [TeamInDB(**team) for team in teams]

@v1_router.get("/teams/{team_id}", response_model=TeamInDB,
          summary="Get a team by ID",
          description="Retrieves a specific team by its unique ID.")
async def get_team(team_id: str):
    """
    Retrieves a single team by its ID.

    - **team_id**: The unique ID of the team.
    """
    team = await _validate_team_exists(team_id)
    return TeamInDB(**team)

@v1_router.put("/teams/{team_id}", response_model=TeamInDB,
          summary="Update a team",
          description="Updates an existing team's information. Only provided fields will be updated.")
async def update_team(team_id: str, team_update: TeamUpdate):
    """
    Updates an existing team.

    - **team_id**: The unique ID of the team to update.
    - **name**: New name (optional).
    - **captain_id**: New ID of the team member who is the captain (optional).
    """
    existing_team = await _validate_team_exists(team_id)

    update_data = team_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update.")

    if "name" in update_data and update_data["name"] != existing_team["name"]:
        # Check if the new name already exists for another team
        duplicate_name_team = await teams_collection.find_one(
            {"name": update_data["name"], "id": {"$ne": team_id}}
        )
        if duplicate_name_team:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A team with the name '{update_data['name']}' already exists."
            )

    if "captain_id" in update_data:
        new_captain_id = update_data["captain_id"]
        if new_captain_id:
            captain_member = await _validate_team_member_exists(new_captain_id)
            # Verify that the new captain belongs to this team
            if team_id not in captain_member.get("team_ids", []):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Team member '{new_captain_id}' does not belong to team '{team_id}'. Cannot be assigned as captain."
                )
        # If captain_id is explicitly set to None, allow it (to remove captain)
        # No need to update the old captain's team_ids as captaincy is now team-centric.

    update_data["updated_at"] = datetime.utcnow()

    updated_team = await teams_collection.find_one_and_update(
        {"id": team_id},
        {"$set": update_data},
        return_document=True
    )

    if not updated_team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found after update attempt.")
    return TeamInDB(**updated_team)

@v1_router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a team",
            description="Deletes a team from the database by its unique ID. Note: This does NOT automatically delete associated team members or coach roles. If this team was a captain's team, the captain_id in the team will be removed. If members were assigned to this team, they will remain assigned until manually updated.")
async def delete_team(team_id: str):
    """
    Deletes a team.

    - **team_id**: The unique ID of the team to delete.
    """
    team = await teams_collection.find_one({"id": team_id})
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    result = await teams_collection.delete_one({"id": team_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found for deletion.")
    
    # Optional: Clean up references to this team in team members and coach roles
    # For team members, if this team was in their team_ids, it will remain there
    # unless explicitly removed by updating the member.
    # For coaches, the team_coach_roles entries will remain until manually deleted.
    # This is a design choice to avoid cascading deletes for simplicity and performance,
    # but in a production system, you might want to implement more robust cleanup.
    return

# --- Coach CRUD Operations ---

@v1_router.post("/coaches", response_model=CoachInDB, status_code=status.HTTP_201_CREATED,
          summary="Create a new coach",
          description="Adds a new coach to the database with a unique ID.")
async def create_coach(coach: CoachCreate):
    """
    Creates a new coach.

    - **name**: Name of the coach.
    - **email**: Unique email address.
    - **phone**: Unique phone number.
    """
    await _validate_email_phone_uniqueness(coaches_collection, coach.email, coach.phone)

    coach_id = str(uuid.uuid4())
    coach_data = coach.model_dump()
    coach_data["id"] = coach_id
    coach_data["created_at"] = datetime.utcnow()
    coach_data["updated_at"] = None

    await coaches_collection.insert_one(coach_data)
    created_coach = await coaches_collection.find_one({"id": coach_id})
    return CoachInDB(**created_coach)

@v1_router.get("/coaches", response_model=List[CoachInDB],
          summary="Get all coaches",
          description="Retrieves a list of all coaches.")
async def get_all_coaches():
    """
    Retrieves all coaches.
    """
    coaches = await coaches_collection.find().to_list(length=None)
    if len(coaches) > 100:
        coaches = coaches[:100]
    return [CoachInDB(**coach) for coach in coaches]

@v1_router.get("/coaches/{coach_id}", response_model=CoachInDB,
          summary="Get a coach by ID",
          description="Retrieves a specific coach by their unique ID.")
async def get_coach(coach_id: str):
    """
    Retrieves a single coach by their ID.

    - **coach_id**: The unique ID of the coach.
    """
    coach = await _validate_coach_exists(coach_id)
    return CoachInDB(**coach)

@v1_router.put("/coaches/{coach_id}", response_model=CoachInDB,
          summary="Update a coach",
          description="Updates an existing coach's information. Only provided fields will be updated.")
async def update_coach(coach_id: str, coach_update: CoachUpdate):
    """
    Updates an existing coach.

    - **coach_id**: The unique ID of the coach to update.
    - **name**: New name (optional).
    - **email**: New email (optional).
    - **phone**: New phone (optional).
    """
    existing_coach = await _validate_coach_exists(coach_id)

    update_data = coach_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update.")

    # Validate uniqueness for email and phone if they are being updated
    if "email" in update_data and update_data["email"] != existing_coach["email"]:
        await _validate_email_phone_uniqueness(coaches_collection, update_data["email"], existing_coach["phone"], coach_id)
    if "phone" in update_data and update_data["phone"] != existing_coach["phone"]:
        await _validate_email_phone_uniqueness(coaches_collection, existing_coach["email"], update_data["phone"], coach_id)
    # If both are updated, validate against both new values
    if "email" in update_data and "phone" in update_data and \
       (update_data["email"] != existing_coach["email"] or update_data["phone"] != existing_coach["phone"]):
        await _validate_email_phone_uniqueness(coaches_collection, update_data["email"], update_data["phone"], coach_id)

    update_data["updated_at"] = datetime.utcnow()

    updated_coach = await coaches_collection.find_one_and_update(
        {"id": coach_id},
        {"$set": update_data},
        return_document=True
    )

    if not updated_coach:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coach not found after update attempt.")
    return CoachInDB(**updated_coach)

@v1_router.delete("/coaches/{coach_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a coach",
            description="Deletes a coach from the database by their unique ID. Note: This does NOT automatically delete associated team coach roles.")
async def delete_coach(coach_id: str):
    """
    Deletes a coach.

    - **coach_id**: The unique ID of the coach to delete.
    """
    coach = await coaches_collection.find_one({"id": coach_id})
    if not coach:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coach not found")

    result = await coaches_collection.delete_one({"id": coach_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coach not found for deletion.")
    
    # Optional: Clean up references to this coach in team_coach_roles
    # For now, the team_coach_roles entries will remain until manually deleted.
    return

# --- Team Coach Role CRUD Operations ---

@v1_router.post("/team-coach-roles", response_model=TeamCoachRoleInDB, status_code=status.HTTP_201_CREATED,
          summary="Assign a coach to a team with a specific role",
          description="Creates a new relationship between a coach and a team, assigning a specific role.")
async def create_team_coach_role(team_coach_role: TeamCoachRoleCreate):
    """
    Assigns a coach to a team with a specific role.

    - **coach_id**: The ID of the coach.
    - **team_id**: The ID of the team.
    - **role**: The role of the coach (HEAD, FITNESS, COACH).
    """
    await _validate_coach_exists(team_coach_role.coach_id)
    await _validate_team_exists(team_coach_role.team_id)

    # Ensure no duplicate role assignment for the same coach and team
    existing_role = await team_coach_roles_collection.find_one(
        {"coach_id": team_coach_role.coach_id, "team_id": team_coach_role.team_id}
    )
    if existing_role:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Coach '{team_coach_role.coach_id}' already has a role assigned to team '{team_coach_role.team_id}'. Use PUT to update."
        )

    role_id = str(uuid.uuid4())
    role_data = team_coach_role.model_dump()
    role_data["id"] = role_id
    role_data["created_at"] = datetime.utcnow()
    role_data["updated_at"] = None

    await team_coach_roles_collection.insert_one(role_data)
    created_role = await team_coach_roles_collection.find_one({"id": role_id})
    return TeamCoachRoleInDB(**created_role)

@v1_router.get("/team-coach-roles", response_model=List[TeamCoachRoleInDB],
          summary="Get all coach-team role assignments",
          description="Retrieves a list of all coach-team role assignments.")
async def get_all_team_coach_roles():
    """
    Retrieves all coach-team role assignments.
    """
    roles = await team_coach_roles_collection.find().to_list(length=None)
    if len(roles) > 100:
        roles = roles[:100]
    return [TeamCoachRoleInDB(**role) for role in roles]

@v1_router.get("/team-coach-roles/{role_id}", response_model=TeamCoachRoleInDB,
          summary="Get a coach-team role assignment by ID",
          description="Retrieves a specific coach-team role assignment by its unique ID.")
async def get_team_coach_role(role_id: str):
    """
    Retrieves a single coach-team role assignment by its ID.

    - **role_id**: The unique ID of the role assignment.
    """
    role = await team_coach_roles_collection.find_one({"id": role_id})
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coach-team role assignment not found")
    return TeamCoachRoleInDB(**role)

@v1_router.put("/team-coach-roles/{role_id}", response_model=TeamCoachRoleInDB,
          summary="Update a coach-team role assignment",
          description="Updates an existing coach-team role assignment. Only provided fields will be updated.")
async def update_team_coach_role(role_id: str, role_update: TeamCoachRoleUpdate):
    """
    Updates an existing coach-team role assignment.

    - **role_id**: The unique ID of the role assignment to update.
    - **role**: New role (optional).
    """
    existing_role = await team_coach_roles_collection.find_one({"id": role_id})
    if not existing_role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coach-team role assignment not found")

    update_data = role_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update.")

    update_data["updated_at"] = datetime.utcnow()

    updated_role = await team_coach_roles_collection.find_one_and_update(
        {"id": role_id},
        {"$set": update_data},
        return_document=True
    )

    if not updated_role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coach-team role assignment not found after update attempt.")
    return TeamCoachRoleInDB(**updated_role)

@v1_router.delete("/team-coach-roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a coach-team role assignment",
            description="Deletes a coach-team role assignment from the database by its unique ID.")
async def delete_team_coach_role(role_id: str):
    """
    Deletes a coach-team role assignment.

    - **role_id**: The unique ID of the role assignment to delete.
    """
    role = await team_coach_roles_collection.find_one({"id": role_id})
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coach-team role assignment not found")

    result = await team_coach_roles_collection.delete_one({"id": role_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coach-team role assignment not found for deletion.")
    return

@v1_router.get("/teams/{team_id}/coaches", response_model=List[CoachInDB],
          summary="Get coaches of a specific team",
          description="Retrieves a list of all coaches associated with a specific team ID and their roles within that team.")
async def get_team_coaches_by_team(team_id: str):
    """
    Retrieves all coaches associated with a specific team, along with their roles.

    - **team_id**: The unique ID of the team.
    """
    await _validate_team_exists(team_id)

    # Find all role assignments for this team
    roles = await team_coach_roles_collection.find({"team_id": team_id}).to_list(length=None)
    
    coach_ids = [role["coach_id"] for role in roles]
    
    # Fetch coach details for the found coach_ids
    coaches_data = await coaches_collection.find({"id": {"$in": coach_ids}}).to_list(length=None)
    
    # Create a dictionary for quick lookup of coaches by ID
    coaches_map = {coach["id"]: CoachInDB(**coach) for coach in coaches_data}
    
    # Optionally, you could enrich the CoachInDB model with the role here if needed,
    # or return a combined model that includes both coach and role details.
    # For simplicity, we'll just return the coaches.
    
    # Filter and return only the coaches found
    result_coaches = [coaches_map[coach_id] for coach_id in coach_ids if coach_id in coaches_map]

    if len(result_coaches) > 100:
        result_coaches = result_coaches[:100]
    return result_coaches


# --- Team Member CRUD Operations (Modified) ---

@v1_router.post("/members", response_model=TeamMemberInDB, status_code=status.HTTP_201_CREATED,
          summary="Create a new team member",
          description="Adds a new team member to the database with a unique ID, optionally assigning them to teams.")
async def create_team_member(member: TeamMemberCreate):
    """
    Creates a new team member.

    - **name**: Name of the team member.
    - **email**: Unique email address.
    - **phone**: Unique phone number.
    - **date_of_birth**: Date of birth.
    - **date_joined**: Date joined.
    - **position**: Player position.
    - **team_ids**: Optional list of IDs of the teams the member belongs to.
    """
    await _validate_email_phone_uniqueness(team_members_collection, member.email, member.phone)
    if member.team_ids:
        await _validate_team_ids_exist(member.team_ids)

    member_id = str(uuid.uuid4())
    member_data = member.model_dump()
    member_data["id"] = member_id
    member_data["created_at"] = datetime.utcnow()
    member_data["updated_at"] = None

    await team_members_collection.insert_one(member_data)
    created_member = await team_members_collection.find_one({"id": member_id})
    return TeamMemberInDB(**created_member)

@v1_router.get("/members", response_model=List[TeamMemberInDB],
          summary="Get all team members (optional: filter by team)",
          description="Retrieves a list of all team members, optionally filtered by a single team ID (members belonging to this team).")
async def get_all_team_members(team_id: Optional[str] = Query(None, description="Optional: Filter members by a single team ID. Returns members who belong to this team.")):
    """
    Retrieves all team members, or members belonging to a specific team.

    - **team_id**: Optional query parameter to filter members by team.
    """
    query_filter = {}
    if team_id:
        await _validate_team_exists(team_id) # Ensure the team_id is valid if provided
        query_filter["team_ids"] = team_id # This will match if team_id is in the team_ids list

    members = await team_members_collection.find(query_filter).to_list(length=None)
    if len(members) > 100:
        members = members[:100]  # Limit to 100 members for performance
    return [TeamMemberInDB(**member) for member in members]

@v1_router.get("/teams/{team_id}/members", response_model=List[TeamMemberInDB],
          summary="Get members of a specific team",
          description="Retrieves a list of all team members belonging to a specific team ID.")
async def get_team_members_by_team(team_id: str):
    """
    Retrieves all team members belonging to a specific team.

    - **team_id**: The unique ID of the team.
    """
    await _validate_team_exists(team_id) # Ensure the team_id is valid

    # Find members where the team_id is in their list of team_ids
    members = await team_members_collection.find({"team_ids": team_id}).to_list(length=None)
    if len(members) > 100:
        members = members[:100]  # Limit to 100 members for performance
    return [TeamMemberInDB(**member) for member in members]


@v1_router.get("/members/{member_id}", response_model=TeamMemberInDB,
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

@v1_router.put("/members/{member_id}", response_model=TeamMemberInDB,
          summary="Update a team member",
          description="Updates an existing team member's information. Only provided fields will be updated.")
async def update_team_member(member_id: str, member_update: TeamMemberUpdate):
    """
    Updates an existing team member.

    - **member_id**: The unique ID of the team member to update.
    - **name**: New name (optional).
    - **email**: New email (optional).
    - **phone**: New phone (optional).
    - **date_of_birth**: New date of birth (optional).
    - **date_joined**: New date joined (optional).
    - **position**: New position (optional).
    - **team_ids**: New list of team IDs (optional).
    """
    existing_member = await team_members_collection.find_one({"id": member_id})
    if not existing_member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")

    update_data = member_update.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields provided for update.")

    # Validate uniqueness for email and phone if they are being updated
    if "email" in update_data and update_data["email"] != existing_member["email"]:
        await _validate_email_phone_uniqueness(team_members_collection, update_data["email"], existing_member["phone"], member_id)
    if "phone" in update_data and update_data["phone"] != existing_member["phone"]:
        await _validate_email_phone_uniqueness(team_members_collection, existing_member["email"], update_data["phone"], member_id)
    # If both are updated, validate against both new values
    if "email" in update_data and "phone" in update_data and \
       (update_data["email"] != existing_member["email"] or update_data["phone"] != existing_member["phone"]):
        await _validate_email_phone_uniqueness(team_members_collection, update_data["email"], update_data["phone"], member_id)


    # Validate new team_ids if provided
    if "team_ids" in update_data and update_data["team_ids"] is not None:
        await _validate_team_ids_exist(update_data["team_ids"])
    elif "team_ids" in update_data and update_data["team_ids"] is None:
        # If team_ids is explicitly set to None, it means clear all teams
        update_data["team_ids"] = []

    update_data["updated_at"] = datetime.utcnow()

    updated_member = await team_members_collection.find_one_and_update(
        {"id": member_id},
        {"$set": update_data},
        return_document=True
    )

    if not updated_member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found after update attempt.")
    return TeamMemberInDB(**updated_member)

@v1_router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete a team member",
            description="Deletes a team member from the database by their unique ID. Note: This does NOT automatically update any teams where this member was a captain.")
async def delete_team_member(member_id: str):
    """
    Deletes a team member.

    - **member_id**: The unique ID of the team member to delete.
    """
    member = await team_members_collection.find_one({"id": member_id})
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")

    result = await team_members_collection.delete_one({"id": member_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found for deletion.")
    
    # Optional: Clean up references to this member as a captain in teams
    # This is a design choice to avoid cascading deletes for simplicity and performance.
    # In a production system, you might want to implement more robust cleanup.
    # For now, if a captain is deleted, the team's captain_id will become a dangling reference.
    return

app.include_router(v1_router)
