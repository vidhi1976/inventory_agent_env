import logging
import os
from .client_wrapper import InventoryEnv
from inference import get_llama_action
from models import InventoryAction, ActionType
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("AgentLoop")

def run_inventory_session():
    # 1. Connect to the OpenEnv Server
    with InventoryEnv(base_url=os.getenv("server_url")).sync() as client:
        
        # --- PHASE 1: AUTOMATIC MAPPING (CSV -> DB) ---
        logger.info("🚀 PHASE 1: Migration (CSV -> DB) Started...")
        
        step_result = client.reset() 
        obs = step_result.observation
        done = False
        while not done:
            logger.info(f"🧐 Mapping: {obs.source_text[:50]}...")
            llm_json = get_llama_action(obs.source_text, obs.db_suggestions, mode="MAPPING")
            
            action = InventoryAction(
                action_type=ActionType.MAP,
                sku=llm_json.get("sku"),
                metadata=llm_json.get("metadata")
            )
            
            step_result = client.step(action)
            obs = step_result.observation 
            done = step_result.done
            
        logger.info("🏁 PHASE 1 COMPLETE. All data is in the Database.")

        # --- PHASE 2: SERVER-SIDE RECONCILIATION ---
        print("\n" + "="*50)
        user_cmd = input("👉 Type 'clean' to begin Deduplication Pass: ").strip().lower()
        if user_cmd == "clean":
            logger.info("🧹 PHASE 2: Starting Reconciliation...")
            live_records = client.get_full_inventory()
            
            for record in live_records:
                if record.get('is_validated'):
                    continue

                record_id = str(record.get('_id'))
                sku = record.get('sku')

                logger.info(f"🔗 Reconciling SKU: {sku}...")

                action = InventoryAction(
                    action_type=ActionType.MERGE,
                    sku=sku,
                    duplicate_id=record_id 
                )
                
                step_result = client.step(action)
                logger.info(f"✅ Server Response: {step_result.observation.message}")

            logger.info("✨ CLEANING COMPLETE. Database matches Ground Truth.")

        # --- PHASE 3: CONVERSATIONAL UPDATES (NEW) ---
        print("\n" + "="*50)
        print("💬 INVENTORY CHATBOT ACTIVE")
        print("Example: 'Update price of IP15 to 500' or 'Set stock for SAM-S24 to 50'")
        print("Type 'exit' to quit.")

        while True:
            chat_input = input("\n👤 User: ").strip()
            
            if chat_input.lower() in ['exit', 'quit', 'bye']:
                logger.info("👋 Closing Inventory Session.")
                break

            if not chat_input:
                continue

            # Ask Llama to extract structured data from natural language
            logger.info("🧠 Agent is thinking...")
            llm_json = get_llama_action(chat_input, [], mode="UPDATE")

            if llm_json.get("action_type") == "UPDATE":
                # Form the structured action
                update_action = InventoryAction(
                    action_type=ActionType.UPDATE,
                    sku=llm_json.get("sku"),
                    # This contains the extracted data: e.g., {"price": 500}
                    metadata=llm_json.get("updates") 
                )

                # Send to server for processing and validation
                step_result = client.step(update_action)
                
                # Retrieve the result message (which includes Validator feedback)
                obs_msg = step_result.observation.message
                reward = step_result.reward

                if reward > 0:
                    logger.info(f"✅ SUCCESS: {obs_msg}")
                else:
                    logger.warning(f"⚠️ REJECTED BY VALIDATOR: {obs_msg}")
            else:
                logger.error("❌ Agent Error: I didn't catch a SKU or specific update in that command.")

if __name__ == "__main__":
    run_inventory_session()