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
        system_prompt = "You are an Inventory Clerk. Respond ONLY with raw JSON. The update can be of price or stock or both."
        user_prompt = f"Message: {source_text}. Format can be of following types depending on the prompt: {{'sku': '...', 'updates': {{'price': 0.0, 'stock': 0}}}} or {{'sku': '...', 'updates': {{'price': 0.0}}}} or {{'sku': '...', 'updates': {{'stock': 0}}}}"
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
    space_url = "https://vidhisingh-inventory-agent-env.hf.space"
    env = InventoryEnv(base_url=space_url)
    
    try:
        # --- PHASE 1: MAPPING ---
        log_start("inventory_mapping", "openenv_ecommerce_challenge", MODEL_NAME)
        phase1_rewards = []
        p1_steps = 0
        result = await env.reset()
        obs = result.observation if hasattr(result, 'observation') else result
        
        while not obs.done:
            llm_json = get_llama_action(client, obs.source_text, mode="MAPPING")
            sku = llm_json.get("sku")
            # if not sku: break
            p1_steps += 1
            action = InventoryAction(
                action_type=ActionType.MAP,
                sku=str(sku),
                metadata=llm_json.get("metadata") if isinstance(llm_json.get("metadata"), dict) else {}
            )
            result = await env.step(action)
            r = getattr(result, 'reward', 0.1)
            phase1_rewards.append(r)
            log_step(p1_steps, json.dumps(llm_json), r, False, None)
            obs = result.observation if hasattr(result, 'observation') else result

        # Close Task 1 before starting Task 2
        p1_score = max(0.01, min(0.99, sum(phase1_rewards)/p1_steps)) if p1_steps > 0 else 0.5
        log_end(p1_score > 0.7, p1_steps, p1_score, phase1_rewards)
        await asyncio.sleep(1) # Critical for parser separation

        # --- PHASE 2: MERGE ---
        log_start("inventory_reconciliation", "openenv_ecommerce_challenge", MODEL_NAME)
        phase2_rewards = []
        p2_steps = 0
        resp = requests.get(f"{space_url}/inventory", timeout=10)
        if resp.status_code == 200:
            live_records = resp.json().get("records", [])
            for record in live_records:
                if record.get('is_validated'): continue
                p2_steps += 1
                action = InventoryAction(
                    action_type=ActionType.MERGE,
                    sku=record.get('sku'),
                    duplicate_id=str(record.get('_id'))
                )
                result = await env.step(action)
                r = getattr(result, 'reward', 0.1)
                phase2_rewards.append(r)
                log_step(p2_steps, f"MERGE_{record.get('sku')}", r, False, None)

        p2_score = max(0.01, min(0.99, sum(phase2_rewards)/p2_steps)) if p2_steps > 0 else 0.5
        log_end(p2_score > 0.7, p2_steps, p2_score, phase2_rewards)
        await asyncio.sleep(1)

        # --- PHASE 3: UPDATE ---
        log_start("inventory_updates", "openenv_ecommerce_challenge", MODEL_NAME)
        phase3_rewards = []
        p3_steps = 0
        chat_queries = ["Update price of APL-IP15-P to 800 "]
        for i, query in enumerate(chat_queries):
            llm_json = get_llama_action(client, query, mode="UPDATE")
            if not llm_json: continue
            p3_steps += 1
            action = InventoryAction(
                action_type=ActionType.UPDATE,
                sku=llm_json.get("sku"),
                metadata=llm_json.get("updates") if isinstance(llm_json.get("updates"), dict) else {}
            )
            result = await env.step(action)
            r = getattr(result, 'reward', 0.1)
            phase3_rewards.append(r)
            is_final = (i == len(chat_queries) - 1)
            log_step(p3_steps, json.dumps(llm_json), r, is_final, None)

        p3_score = max(0.01, min(0.99, sum(phase3_rewards)/p3_steps)) if p3_steps > 0 else 0.5
        log_end(p3_score > 0.7, p3_steps, p3_score, phase3_rewards)

    finally:
        await env.close()
if __name__ == "__main__":
    asyncio.run(main())