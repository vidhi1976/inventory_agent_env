import logging
from typing import Dict, Any
from openenv.core import EnvClient
from openenv.core.client_types import StepResult

from openenv.core.env_server.types import State
from dotenv import load_dotenv
load_dotenv()

# Shared models from root
from models import InventoryAction, InventoryObservation

# --- Setup Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("InventoryClient")

class InventoryEnv(
    EnvClient[InventoryAction, InventoryObservation, State]
):
    """
    Enhanced Client for the Automated E-Commerce Inventory Manager with Logging.
    """

    def _step_payload(self, action: InventoryAction) -> Dict[str, Any]:
        """
        Serializes Action and logs the intent.
        """
        payload = {
            "action_type": action.action_type.value,
            "sku": action.sku,
            "primary_id": action.primary_id,
            "duplicate_id": action.duplicate_id,
            "stock_delta": action.stock_delta,
            "metadata": action.metadata,
        }
        
        logger.info(f"🚀 SENDING ACTION: {action.action_type.value} | SKU: {action.sku or 'N/A'}")
        return payload

    def _parse_result(self, payload: Dict[str, Any]) -> StepResult[InventoryObservation]:
        """
        Parses result and logs the Environment's feedback/reward.
        """
        obs_data = payload.get("observation", {})
        reward = payload.get("reward", 0.0)
        done = payload.get("done", False)

        observation = InventoryObservation(
            source_text=obs_data.get("source_text", ""),
            task_difficulty=obs_data.get("task_difficulty", "easy"),
            db_suggestions=obs_data.get("db_suggestions", []),
            done=done,
            reward=reward,
            message=obs_data.get("message", ""),
        )

        # --- LOGGING THE FEEDBACK ---
        log_msg = f"📥 REWARD: {reward} | DONE: {done} | MSG: {observation.message}"
        if reward > 0:
            logger.info(f"✅ SUCCESS: {log_msg}")
        elif reward < 0:
            logger.warning(f"⚠️ PENALTY: {log_msg}")
        else:
            logger.info(log_msg)

        return StepResult(
            observation=observation,
            reward=reward,
            done=done,
        )

    def _parse_state(self, payload: Dict[str, Any]) -> State:

        state = State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )
        logger.debug(f"📊 STATE: Episode {state.episode_id} | Step {state.step_count}")
        return state
    def get_full_inventory(self) -> list:
        """
        Custom API call to fetch all live records from the server.
        """
        import httpx
        # We use the base_url provided during initialization
        response = httpx.get(f"{self.base_url}/inventory")
        if response.status_code == 200:
            return response.json().get("records", [])
        else:
            logger.error(f"❌ Failed to fetch inventory: {response.text}")
            return []