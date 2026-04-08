import logging
from uuid import uuid4
import asyncio
from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

# Import your helper classes
from db_utils import InventoryDB
from validator import validate_action
try:
    from ..models import InventoryAction, InventoryObservation, ActionType
except (ImportError, ValueError):
    from models import InventoryAction, InventoryObservation, ActionType

logger = logging.getLogger("InventoryEnv")

class MyEnvironment(Environment):
    """
    The Automated E-Commerce Environment.
    Manages the lifecycle of a cleaning task: Reset -> Observe -> Step -> Reward.
    """
    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self.db = InventoryDB()
        self.current_data_pointer = 0  # To track which CSV row to send next
        self.all_rows = []

    
    def reset(self) -> InventoryObservation:
        """
        Wipes MongoDB (Live Inventory) and prepares for the first CSV mapping task.
        """
        # 1. Reset Internal State
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self.current_data_pointer = 0
        
        # 2. CLEAR the Live Inventory (Do NOT re-seed dirty data here)
        # We only call the DB to ensure we start with a blank slate
        self.db.clear_live_inventory() 
        
        # 3. Load the CSV rows but keep them in MEMORY (not in the DB)
        # This becomes the Agent's "Task List"
        self.all_rows = self.db.get_csv_rows() 
        
        if not self.all_rows:
            return InventoryObservation(done=True, message="Error: CSV empty.")

        # 4. Get the first row from the CSV memory
        first_row = self.all_rows[self.current_data_pointer]
        
        # 5. Search for suggestions in the Ground Truth (to help with mapping)
        # Note: We search against the master catalog, not the dirty collection
        # suggestions = self.db.find_suggestions(first_row.get('title', ''))
        suggestions = self.db.find_suggestions(first_row.get('title', ''), first_row.get('supplier_sku', ''))

        return InventoryObservation(
            source_text=str(first_row),
            task_difficulty="easy", # Mapping is the 'Easy' entry task
            db_suggestions=suggestions,
            done=False,
            reward=0.0,
            message="Environment Ready: Starting migration/mapping from CSV to DB."
        )
    def step(self, action: InventoryAction) -> InventoryObservation:
        self._state.step_count += 1
        
        result_msg = ""
        reward = 0.0
        validation_msg = ""

        # 1. Branch Logic based on Action Type
        if action.action_type == ActionType.MAP:
            # PURE MAPPING: No validation check against Ground Truth
            self.db.add_product(action.sku, action.metadata)
            result_msg = f"Mapped SKU: {action.sku}"
            
            # During the Mapping Phase, we give a standard reward for successful format transfer
            reward = 1.0 
            validation_msg = "✅ Schema Mapping complete."

        elif action.action_type == ActionType.MERGE:
            # MERGE: This IS where we want to validate
            self.db.merge_products( action.duplicate_id)
            result_msg = "Products Merged"
            
            # Only run validation logic for MERGE/UPDATE
            reward, validation_msg = validate_action(
                action.action_type.value, 
                action.sku, 
                action.metadata
            )
        elif action.action_type == ActionType.UPDATE:
            # 1. Database Update
            success, result_msg = self.db.update_product(action.sku, action.metadata)
            
            # 2. Validation
            # We pass the metadata (the changes) to the validator
            reward, validation_msg = validate_action(
                action.action_type.value, 
                action.sku, 
                action.metadata,
                self.db # Pass db helper for Ground Truth lookups
            )
            
            return InventoryObservation(
                source_text=f"Update Request for {action.sku}",
                message=f"{result_msg} | {validation_msg}",
                reward=reward,
                done=False # Keep the session alive for more chat
            )
        # 2. Advance the pointer (The "Task List")
        self.current_data_pointer += 1
        is_done = self.current_data_pointer >= len(self.all_rows)
        
        # 3. Get next observation or finish
        next_obs_text = ""
        next_suggestions = []
        if not is_done:
            next_row = self.all_rows[self.current_data_pointer]
            next_obs_text = str(next_row)
            # Fetch suggestions to help with the NEXT decision
            next_suggestions = self.db.find_suggestions(
                next_row.get('title', ''), 
                next_row.get('supplier_sku', '')
            )

        return InventoryObservation(
            source_text=next_obs_text,
            task_difficulty="easy",
            db_suggestions=next_suggestions,
            done=is_done,
            reward=reward,
            message=f"{result_msg} | {validation_msg}"
        )
    @property
    def state(self) -> State:
        return self._state