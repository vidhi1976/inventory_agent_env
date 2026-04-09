import asyncio
import os
import json
import sys
import requests
from openai import OpenAI
from client.client_wrapper import InventoryEnv
from models import InventoryAction, InventoryObservation, ActionType 

# 1. Captured Globally (This worked for your parsing check)
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


# def get_llama_action(client, source_text, mode="MAPPING") -> dict:
#     system_prompt = "You are an Inventory Assistant. Respond ONLY with raw JSON."
#     user_prompt = f"{mode} this: {source_text}. Format: {{'sku': '...', 'metadata/updates': {{...}}}}"

#     try:
#         completion = client.chat.completions.create(
#             model=MODEL_NAME,
#             messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
#             temperature=0.1
#         )
#         content = completion.choices[0].message.content
#         content = content.replace("```json", "").replace("```", "").strip()
#         return json.loads(content)
#     except Exception:
#         return {}

# --- MAIN EXECUTION ---
async def main():
    if not all([API_BASE_URL, API_KEY]):
        return

    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)
    
    # 2. FIXED URLS: No brackets, no parentheses, just the raw string
    space_url = "https://vidhisingh-inventory-agent-env.hf.space"
    env = InventoryEnv(base_url=space_url)
    
    rewards, steps, success, score = [], 0, False, 0.0
    
    # 3. Log Start BEFORE any network calls
    
    try:
        # --- PHASE 1: MAPPING ---
        log_start("inventory_mapping", "openenv_ecommerce_challenge", MODEL_NAME)
        result = await env.reset()
        obs = result.observation if hasattr(result, 'observation') else result
        
        while not obs.done:
            llm_json = get_llama_action(client, obs.source_text, mode="MAPPING")
            sku = llm_json.get("sku")
            metadata = llm_json.get("metadata")
            if not sku:
                print(f"⚠️ Skipping row: LLM failed to extract SKU from {obs.source_text[:30]}...")
                # You might need to trigger a dummy step or break depending on env logic
                break
            steps += 1
            action = InventoryAction(
                action_type=ActionType.MAP,
                sku=str(sku),
                metadata=metadata if isinstance(metadata, dict) else {}
            )
            
            result = await env.step(action)
            obs = result.observation if hasattr(result, 'observation') else result
            reward = getattr(result, 'reward', 0.0)
            rewards.append(reward)
            log_step(steps, json.dumps(llm_json), reward, False, None)

        # --- PHASE 2: MERGE ---
        log_start("inventory_reconciliation", "openenv_ecommerce_challenge", MODEL_NAME)
        steps = 0
        resp = requests.get(f"{space_url}/inventory", timeout=10)
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
                rewards.append(getattr(result, 'reward', 0.0))
                log_step(steps, f"MERGE_{record.get('sku')}", rewards[-1], False, None)

        # --- PHASE 3: UPDATE ---
        log_start("inventory_updates", "openenv_ecommerce_challenge", MODEL_NAME)
        steps=0
        chat_queries = ["Update price of APL-IP15-P to 800 and stock to 2"]
        for i, query in enumerate(chat_queries):
            llm_json = get_llama_action(client, query, mode="UPDATE")
            if not llm_json: continue
            steps += 1
            action = InventoryAction(
                action_type=ActionType.UPDATE,
                sku=llm_json.get("sku"),
                metadata=llm_json.get("updates")if isinstance(llm_json.get("updates"), dict) else {}
            )
            result = await env.step(action)
            rewards.append(getattr(result, 'reward', 0.0))
            is_final = (i == len(chat_queries) - 1)
            log_step(steps, json.dumps(llm_json), rewards[-1], is_final, None)

        score = sum(rewards) / steps if steps > 0 else 0
        success = score > 0.7

    finally:
        await env.close()
        log_end(success, steps, score, rewards)

if __name__ == "__main__":
    asyncio.run(main())