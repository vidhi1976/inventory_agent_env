import asyncio
import os
import json
from openai import OpenAI
from dotenv import load_dotenv
import inspect
import sys
from openenv.core.env_client import EnvClient
from client.client_wrapper import InventoryEnv

server_dir = os.path.join(os.path.dirname(__file__), "server")
if server_dir not in sys.path:
    sys.path.append(server_dir)
# Import your specific environment and actions
from server.my_env_environment import MyEnvironment
from models import InventoryAction, InventoryObservation, ActionType 

load_dotenv()

# --- CONFIGURATION ---
API_BASE_URL = os.getenv("API_BASE_URL", "https://api.groq.com/openai/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "llama-3.3-70b-versatile")
API_KEY =os.getenv("GROQ_API_KEY") or os.getenv("HF_TOKEN") 


# --- HACKATHON LOGGING ---
def log_start(task, env, model): print(f"[START] task={task} env={env} model={model}", flush=True)
def log_step(step, action, reward, done, error):
    print(f"[STEP] step={step} action={action} reward={reward:.2f} done={str(done).lower()} error={error or 'null'}", flush=True)
def log_end(success, steps, score, rewards):
    print(f"[END] success={str(success).lower()} steps={steps} score={score:.2f} rewards={','.join(f'{r:.2f}' for r in rewards)}", flush=True)

# --- LLM ACTION GENERATOR ---
def get_llama_action(client, source_text, mode="MAPPING") -> dict:
    if mode == "MAPPING":
        system_prompt = "You are an Inventory Mapper. Map CSV to JSON. Respond ONLY with JSON."
        user_prompt = f"Map this row: {source_text}. Structure: {{'sku': '...', 'metadata': {{'name': '...', 'price': 0.0, 'stock': 0}}}}"
    else: # UPDATE
        system_prompt = "You are an Inventory Clerk. Extract SKU and updates. Respond ONLY with JSON."
        user_prompt = f"Message: {source_text}. Structure: {{'sku': '...', 'updates': {{'price': 0.0, 'stock': 0}}}}"

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except Exception:
        return {}

# --- MAIN EXECUTION ---
async def main():
    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)
    env = InventoryEnv(base_url="https://vidhisingh-inventory-agent-env.hf.space")
    # env = EnvClient(base_url="https://vidhisingh-inventory-agent-env.hf.space")
    # env = MyEnvironment(base_url="https://vidhisingh-inventory-agent-env.hf.space")
    rewards, steps, success, score = [], 0, False, 0.0
    
    log_start("automated_inventory_management", "openenv_ecommerce_challenge", MODEL_NAME)

    try:
        # --- PHASE 1: MAPPING ---
        
        result = await env.reset()
        obs = result.observation if hasattr(result, 'observation') else result
        
        while not obs.done:
            steps += 1
            llm_json = get_llama_action(client, obs.source_text, mode="MAPPING")
            
            action = InventoryAction(
                action_type=ActionType.MAP,
                sku=llm_json.get("sku"),
                metadata=llm_json.get("metadata")
            )
            
            result = await env.step(action)
            obs = result.observation if hasattr(result, 'observation') else result
            rewards.append(getattr(result, 'reward', 0.0))
            log_step(steps, json.dumps(llm_result := llm_json), rewards[-1], False, None)

        # --- PHASE 2: DETERMINISTIC MERGE ---
        print("\n--- STARTING DETERMINISTIC DEDUPLICATION ---", flush=True)
        # Using the actual server logic to get inventory
        # Note: If env doesn't have get_full_inventory, we skip to Phase 3
        import requests
        
        # Hit the custom endpoint you added to app.py
        resp = requests.get("https://vidhisingh-inventory-agent-env.hf.space/inventory")
        
        if resp.status_code == 200:
            live_records = resp.json().get("records", [])
            for record in live_records:
                if record.get('is_validated'): continue
                steps += 1
                
                # This 'env.step' sends the merge command to the HF Space
                action = InventoryAction(
                    action_type=ActionType.MERGE,
                    sku=record.get('sku'),
                    duplicate_id=str(record.get('_id'))
                )
                result = await env.step(action)
                rewards.append(getattr(result, 'reward', 0.0))
                log_step(steps, "REMOTE_MERGE", rewards[-1], False, None)
        # --- PHASE 3: CHAT UPDATES ---
        print("\n--- STARTING CHAT UPDATES ---", flush=True)
        chat_queries = ["Update price of APL-IP15-P to 1050"] # You can add more here
        
        for query in chat_queries:
            steps += 1
            llm_json = get_llama_action(client, query, mode="UPDATE")
            
            # FIX: Mapping 'updates' from LLM to 'metadata' for InventoryAction
            action = InventoryAction(
                action_type=ActionType.UPDATE,
                sku=llm_json.get("sku"),
                metadata=llm_json.get("updates") # This matches your old loop's logic
            )
            
            result = await env.step(action)
            rewards.append(getattr(result, 'reward', 0.0))
            log_step(steps, json.dumps(llm_json), rewards[-1], True, None)

        score = sum(rewards) / steps if steps > 0 else 0
        success = score > 0.7

    finally:
        await env.close()
        log_end(success, steps, score, rewards)

if __name__ == "__main__":
    asyncio.run(main())