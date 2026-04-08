import os
import json
import logging
from difflib import SequenceMatcher

logger = logging.getLogger("Validator")

def validate_action(action_type: str, sku: str, provided_data: dict, db_helper=None):
    """
    Compares Agent actions against ground_truth.json to calculate RL rewards.
    Handles MAPPING, MERGING, and CONVERSATIONAL UPDATES.
    """
    base_dir = os.path.dirname(__file__)
    truth_path = "/app/data/ground_truth.json" if os.path.exists("/app/data/ground_truth.json") else os.path.join(base_dir, "..", "data", "ground_truth.json")
    # Ensure this path matches your project structure
    # truth_path = os.path.join(base_dir, "..", "data", "ground_truth.json")

    try:
        with open(truth_path, 'r') as f:
            truth_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"❌ Validator cannot find ground_truth at {truth_path}")
        return 0.0, "System Error: Truth file missing."

    # --- 1. SEARCH LOGIC: Find the Master Record ---
    master_record = None
    # Attempt A: Exact SKU match
    master_record = next((item for item in truth_data if item["sku"] == sku), None)
    
    # Attempt B: Partial SKU match
    if not master_record:
        master_record = next((item for item in truth_data if sku in item["sku"] or item["sku"] in sku), None)
    
    # Attempt C: Name similarity
    if not master_record and provided_data.get('name'):
        master_record = next((item for item in truth_data if 
                             SequenceMatcher(None, str(provided_data.get('name')).lower(), 
                                            item['name'].lower()).ratio() > 0.8), None)

    # If no match found in Master Catalog
    if not master_record:
        return -0.5, f"Hallucination: SKU '{sku}' has no relation to Master Catalog."

    # --- 2. REWARD LOGIC: Based on Action Type ---

    # --- MAPPING & MERGING ---
    if action_type in ["MAP", "MERGE"]:
        if sku == master_record["sku"]:
            return 1.0, f"✅ Perfect: Action applied using Master SKU: {sku}"
        else:
            return 0.7, f"⚠️ Partial: Used Supplier SKU '{sku}'. Expected Master SKU '{master_record['sku']}'."

    # --- CONVERSATIONAL UPDATES ---
    if action_type == "UPDATE":
        # Check 1: Price Sanity
        if "price" in provided_data:
            try:
                price = float(provided_data["price"])
                if price <= 0:
                    return -1.0, "❌ Invalid Price: Price must be positive."
                
                # Compare against Master Price in Ground Truth
                master_price = float(master_record.get('price', 0))
                if master_price > 0 and price < (master_price * 0.2):
                    return -0.5, f"⚠️ Warning: Price ${price} is suspiciously low compared to Master ${master_price}."
            except ValueError:
                return -1.0, "❌ Price must be a valid number."

        # Check 2: Stock Sanity
        if "stock" in provided_data:
            try:
                stock = int(provided_data["stock"])
                if stock < 0:
                    return -1.0, "❌ Invalid Stock: Cannot have negative inventory."
            except ValueError:
                return -1.0, "❌ Stock must be an integer."

        return 1.0, f"✅ Update Verified for SKU {sku}."

    return -0.1, f"Unknown Action Type: {action_type}"


if(__name__ == "__main__"):
    # Quick local test
    reward, msg = validate_action("MAP", "APL-IP15-P", {"name": "Apple iPhone 15 Pro"}, None)
    print(f"Reward: {reward}, Message: {msg}"   )