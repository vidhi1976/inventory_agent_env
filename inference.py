import asyncio
import os
import json
import logging
import sys
import requests
from openai import OpenAI
from client.client_wrapper import InventoryEnv
from models import InventoryAction, InventoryObservation, ActionType 

# --- HACKATHON LOGGING ---
def log_start(task, env, model): 
    print(f"[START] task={task} env={env} model={model}", flush=True)

def log_step(step, action, reward, done, error):
    print(f"[STEP] step={step} action={action} reward={reward:.2f} done={str(done).lower()} error={error or 'null'}", flush=True)

def log_end(success, steps, score, rewards):
    print(f"[END] success={str(success).lower()} steps={steps} score={score:.2f} rewards={','.join(f'{r:.2f}' for r in rewards)}", flush=True)

# --- LLM ACTION GENERATOR ---
def get_llama_action(client, model_to_use, source_text, mode="MAPPING") -> dict:
    if mode == "MAPPING":
        system_prompt = "You are an Inventory Mapper. Respond ONLY with raw JSON."
        user_prompt = f"Map: {source_text}. Format: {{'sku': '...', 'metadata': {{'name': '...', 'price': 0.0, 'stock': 0}}}}"
    else: 
        system_prompt = "You are an Inventory Clerk. Respond ONLY with raw JSON."
        user_prompt = f"Message: {source_text}. Format: {{'sku': '...', 'updates': {{'price': 0.0, 'stock': 0}}}}"

    try:
        completion = client.chat.completions.create(
            model=model_to_use,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.1
        )
        content = completion.choices[0].message.content
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except Exception as e:
        sys.stderr.write(f"LLM Error: {e}\n")
        return {}

# --- MAIN EXECUTION ---
async def main():
    # 1. Capture Platform Variables
    base_url = os.environ.get("API_BASE_URL")
    model_name = os.environ.get("MODEL_NAME")
    api_key = os.environ.get("API_KEY")

    if not all([base_url, model_name, api_key]):
        sys.stderr.write("CRITICAL: Missing API environment variables\n")
        return

    # 2. Setup Client & Environment
    client = OpenAI(base_url=base_url, api_key=api_key)
    
    # CLEAN URL - Plain string only
    space_url = "https://vidhisingh-inventory-agent-env.hf.space"
    env = InventoryEnv(base_url=space_url)
    
    rewards, steps, success, score = [], 0, False, 0.0
    
    try:
        # LOG START - Must be the first thing printed to stdout
        log_start("automated_inventory_management", "openenv_ecommerce_challenge", model_name)

        # --- PHASE 1: MAPPING ---
        result = await env.reset()
        obs = result.observation if hasattr(result, 'observation') else result
        
        while not obs.done:
            llm_json = get_llama_action(client, model_name, obs.source_text, mode="MAPPING")
            if not llm_json or "sku" not in llm_json:
                break 
                
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
        resp = requests.get(f"{space_url}/inventory", timeout=15)
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
        chat_queries = ["Update price of APL-IP15-P to 800 and stock to 2"]
        for i, query in enumerate(chat_queries):
            llm_json = get_llama_action(client, model_name, query, mode="UPDATE")
            if not llm_json or "sku" not in llm_json: continue

            steps += 1
            action = InventoryAction(
                action_type=ActionType.UPDATE,
                sku=llm_json.get("sku"),
                metadata=llm_json.get("updates")
            )
            
            result = await env.step(action)
            reward = getattr(result, 'reward', 0.0)
            rewards.append(reward)
            is_final = (i == len(chat_queries) - 1)
            log_step(steps, json.dumps(llm_json), reward, is_final, None)

        score = sum(rewards) / steps if steps > 0 else 0
        success = score > 0.7

    except Exception as e:
        sys.stderr.write(f"Runtime Error: {e}\n")
    finally:
        await env.close()
        # ALWAYS log end to satisfy validator
        log_end(success, steps, score, rewards)

if __name__ == "__main__":
    asyncio.run(main())