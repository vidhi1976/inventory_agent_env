import asyncio
import os
import json
import logging
import sys
import requests
from openai import OpenAI
from dotenv import load_dotenv
from client.client_wrapper import InventoryEnv
from models import InventoryAction, InventoryObservation, ActionType 

# load_dotenv()
logger = logging.getLogger("InferenceModule")

# --- CONFIGURATION (STRICTLY FROM ENV) ---
API_BASE_URL = os.environ.get("API_BASE_URL")
MODEL_NAME = os.environ.get("MODEL_NAME")
API_KEY = os.environ.get("API_KEY")

# --- HACKATHON LOGGING ---
def log_start(task, env, model): print(f"[START] task={task} env={env} model={model}", flush=True)
def log_step(step, action, reward, done, error):
    print(f"[STEP] step={step} action={action} reward={reward:.2f} done={str(done).lower()} error={error or 'null'}", flush=True)
def log_end(success, steps, score, rewards):
    print(f"[END] success={str(success).lower()} steps={steps} score={score:.2f} rewards={','.join(f'{r:.2f}' for r in rewards)}", flush=True)

# --- LLM ACTION GENERATOR ---
def get_llama_action(client, source_text, mode="MAPPING") -> dict:
    if mode == "MAPPING":
        system_prompt = "You are an Inventory Mapper. Respond ONLY with raw JSON."
        user_prompt = f"Map this row: {source_text}. Format: {{'sku': '...', 'metadata': {{'name': '...', 'price': 0.0, 'stock': 0}}}}"
    else: # UPDATE
        system_prompt = "You are an Inventory Clerk. Respond ONLY with raw JSON."
        user_prompt = f"Message: {source_text}. Format: {{'sku': '...', 'updates': {{'price': 0.0, 'stock': 0}}}}"

    try:
        # response_format removed to prevent 400 Bad Request on proxy
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.1
        )
        content = completion.choices[0].message.content
        # Remove markdown code blocks if the LLM adds them
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except Exception as e:
        sys.stderr.write(f"LLM Error: {e}\n")
        return {}

# --- MAIN EXECUTION ---
async def main():
    if not API_BASE_URL or not API_KEY:
        sys.stderr.write("Missing environment variables\n")
        return

    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)
    # Ensure this URL is reachable by the platform's validator
    env = InventoryEnv(base_url="[https://vidhisingh-inventory-agent-env.hf.space](https://vidhisingh-inventory-agent-env.hf.space)")
    
    rewards, steps, success, score = [], 0, False, 0.0
    log_start("automated_inventory_management", "openenv_ecommerce_challenge", MODEL_NAME)

    try:
        # --- PHASE 1: MAPPING ---
        result = await env.reset()
        obs = result.observation if hasattr(result, 'observation') else result
        
        while not obs.done:
            llm_json = get_llama_action(client, obs.source_text, mode="MAPPING")
            if not llm_json or "sku" not in llm_json:
                break # Stop if we can't get valid JSON
                
            steps += 1
            action = InventoryAction(
                action_type=ActionType.MAP,
                sku=llm_json.get("sku"),
                metadata=llm_json.get("metadata")
            )
            
            result = await env.step(action)
            obs = result.observation if hasattr(result, 'observation') else result
            reward = getattr(result, 'reward', 0.0)
            rewards.append(reward)
            log_step(steps, json.dumps(llm_json), reward, False, None)

        # --- PHASE 2: DETERMINISTIC MERGE ---
        print("\n--- STARTING DETERMINISTIC DEDUPLICATION ---", flush=True)
        resp = requests.get("[https://vidhisingh-inventory-agent-env.hf.space/inventory](https://vidhisingh-inventory-agent-env.hf.space/inventory)", timeout=10)

        if resp.status_code == 200:
            live_records = resp.json().get("records", [])
            for record in live_records:
                if record.get('is_validated'): continue
                steps += 1
                action = InventoryAction(
                    action_type=ActionType.MERGE,
                    sku=record.get('sku'),
                    duplicate_id=str(record.get('_id'))
                )
                result = await env.step(action)
                reward = getattr(result, 'reward', 0.0)
                rewards.append(reward)
                log_step(steps, f"MERGE_{record.get('sku')}", reward, False, None)

        # --- PHASE 3: CHAT UPDATES ---
        print("\n--- STARTING CHAT UPDATES ---", flush=True)
        chat_queries = ["Update price of APL-IP15-P to 800 and stock to 2"]
        
        for i, query in enumerate(chat_queries):
            llm_json = get_llama_action(client, query, mode="UPDATE")
            if not llm_json or "sku" not in llm_json:
                continue

            steps += 1
            action = InventoryAction(
                action_type=ActionType.UPDATE,
                sku=llm_json.get("sku"),
                metadata=llm_json.get("updates")
            )
            
            result = await env.step(action)
            reward = getattr(result, 'reward', 0.0)
            rewards.append(reward)
            # Final step: Set done=True
            is_final = (i == len(chat_queries) - 1)
            log_step(steps, json.dumps(llm_json), reward, is_final, None)

        score = sum(rewards) / steps if steps > 0 else 0
        success = score > 0.7

    except Exception as e:
        sys.stderr.write(f"Runtime Error: {e}\n")
    finally:
        await env.close()
        log_end(success, steps, score, rewards)

if __name__ == "__main__":
    asyncio.run(main())