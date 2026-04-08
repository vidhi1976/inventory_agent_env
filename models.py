from enum import Enum
from typing import Dict, List, Optional, Any
from openenv.core.env_server.types import Action, Observation
from pydantic import Field

# --- Enums for Strict Logic ---

class ActionType(str, Enum):
    MAP = "MAP"                # Easy: Initial mapping of CSV to DB
    MERGE = "MERGE"            # Medium: Deduplicating similar products
    UPDATE = "UPDATE"          # Hard: Adjusting stock from email text
    SKIP = "SKIP"              # For when data is too corrupt to process

# --- The Shared Contract ---

class InventoryAction(Action):
    """
    The Action sent by the Llama Agent to the OpenEnv Server.
    """
    action_type: ActionType = Field(..., description="The type of operation to perform")
    
    # Payload fields (Optional depending on the task)
    sku: Optional[str] = Field(None, description="The SKU to target or create")
    primary_id: Optional[str] = Field(None, description="Target ID for MERGE tasks")
    duplicate_id: Optional[str] = Field(None, description="Source ID to be deleted in MERGE")
    stock_delta: Optional[int] = Field(None, description="Amount to add/subtract for UPDATE_STOCK")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional product details")


class InventoryObservation(Observation):
    """
    The data the Llama Agent 'sees' at each step.
    """
    # Current Task Data
    source_text: str = Field(..., description="The CSV row or Email text to process")
    task_difficulty: str = Field(default="easy", description="Current level: easy, medium, or hard")
    
    # Contextual Data (The 'MDP' part)
    db_suggestions: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="Top 3 matches found in MongoDB for this item"
    )
    
    # Standard RL Fields
    done: bool = Field(default=False, description="Whether the episode is finished")
    reward: Optional[float] = Field(None, description="Reward from the PREVIOUS action")
    message: str = Field(default="", description="Feedback from the server (e.g., 'Merge Successful')")