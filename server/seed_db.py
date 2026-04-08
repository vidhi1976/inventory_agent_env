import json
import csv
import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "ecommerce_inventory")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

async def seed_database():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    
    print(f"Connecting to MongoDB at {MONGO_URI}...")

    # --- 1. Seed Ground Truth (The Answer Key) ---
    gt_path = os.path.join(DATA_DIR, "ground_truth.json")
    if os.path.exists(gt_path):
        with open(gt_path, 'r') as f:
            ground_truth = json.load(f)
        
        await db.ground_truth.delete_many({}) # Clear old data
        await db.ground_truth.insert_many(ground_truth)
        print(f"✅ Loaded {len(ground_truth)} records into 'ground_truth' collection.")
    else:
        print(f"❌ Error: {gt_path} not found.")

    # --- 2. Seed Inventory (The 'Dirty' Data for Agent) ---
    csv_path = os.path.join(DATA_DIR, "supplier_products.csv")
    if os.path.exists(csv_path):
        dirty_items = []
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Basic cleaning for DB types
                row['price'] = float(row['price']) if row['price'] else 0.0
                row['stock'] = 0 # Starting stock for all dirty items
                dirty_items.append(row)
        
        await db.inventory.delete_many({}) # Clear old workspace
        if dirty_items:
            await db.inventory.insert_many(dirty_items)
            print(f"✅ Loaded {len(dirty_items)} records into 'inventory' collection.")
    else:
        print(f"❌ Error: {csv_path} not found.")

    print("\n🚀 Database seeding complete. You can now view these in Mongo Express at http://localhost:8081")

if __name__ == "__main__":
    asyncio.run(seed_database())