import json
import os
import csv
import logging
from pymongo import MongoClient, ASCENDING
from bson import ObjectId  # Move this to the very top

logger = logging.getLogger("InventoryDB")

class InventoryDB:
    def __init__(self):
        self.uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
        self.client = MongoClient(self.uri)
        self.db = self.client["ecommerce_inventory"]
        self.collection = self.db["inventory"]
    def clear_live_inventory(self):
        """
        Hard reset of the live inventory collection.
        Used at the start of a Mapping/Migration session.
        """
        result = self.collection.delete_many({})
        print(f"🗑️ Live Inventory Cleared. Documents removed: {result.deleted_count}")
        return result.deleted_count

    def get_csv_rows(self):
        """
        Reads the supplier CSV and returns rows as a list of dicts.
        This provides the 'Raw' tasks for the Agent to map.
        """
        csv_items = []
        
        csv_path = os.getenv("CSV_PATH", "/app/env/data/supplier_products.csv")
        if not os.path.exists(csv_path):
            print(f"❌ CSV not found at {csv_path}")
            return []

        with open(csv_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                # Basic cleaning for the 'Observation'
                row['price'] = float(row.get('price', 0))
                row['stock'] = int(row.get('stock', 0))
                csv_items.append(row)
        return csv_items
    def reset_to_initial_state(self):
        """Wipes DB and re-seeds from CSV."""
        self.collection.delete_many({})
        # dirty_items = []
        # csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'supplier_products.csv')
        
        # with open(csv_path, mode='r', encoding='utf-8') as file:
        #     reader = csv.DictReader(file)
        #     for row in reader:
        #         row['price'] = float(row['price'])
        #         row['stock'] = int(row['stock']) 
        #         dirty_items.append(row)
        
        # if dirty_items:
        #     self.collection.insert_many(dirty_items)
        return []

    # def find_suggestions(self, title: str):
    #     """Finds similar items to help Llama decide on MERGE."""
    #     cursor = self.collection.find({"title": {"$regex": title[:5], "$options": "i"}}).limit(3)
    #     suggestions = list(cursor)
    #     for s in suggestions:
    #         s['_id'] = str(s['_id'])
    #     logger.info(f"these are the suggestions: {suggestions}")
    #     return suggestions

    # def add_product(self, sku, metadata):
    #     """Standard MAP action logic."""
    #     product = {
    #         "sku": sku, 
    #         "title": metadata.get('title'), 
    #         "price": float(metadata.get('price', 0)), 
    #         "supplier_sku": metadata.get('supplier_sku'),
    #         "stock": int(metadata.get('stock', 0))
    #     }
    #     return self.collection.insert_one(product)
    def add_product(self, sku, metadata):
        clean_mapped_record = {
            "sku": sku,
            "name": metadata.get("name", "Unknown"),
            "category": metadata.get("category", "N/A"),
            "price": float(metadata.get("price", 0.0)),
            "stock": int(metadata.get("stock", 0)),
            "is_validated": False 
        }
        # Use update_one with upsert=True to FORCE the write
        return self.collection.update_one(
            {"sku": sku, "is_validated": False}, 
            {"$set": clean_mapped_record}, 
            upsert=True
        )
    def update_product(self, sku, updates: dict):
        """
        Updates specific fields for a validated record.
        'updates' can contain 'price', 'stock', or both.
        """
        print(f"DEBUG: Entering update_product for {sku}", flush=True)
        if not sku:
            return False, "No SKU provided for update."

        # Perform the update in the Live Inventory
        result = self.collection.update_one(
            {"sku": sku, "is_validated": True},
            {"$set": updates}
        )
        print(f"DEBUG ATLAS: Updated {sku}. Matched: {result.matched_count}, Modified: {result.modified_count}")
        if result.modified_count > 0:
            return True, f"Successfully updated {list(updates.keys())} for {sku}."
        return False, f"SKU {sku} not found or no changes made."
    def find_suggestions(self, title: str, supplier_sku: str = None):
        """
        Finds the official Master Record using the SKU as the primary key.
        """
        # 1. Try to find an EXACT match in Ground Truth using the SKU
        if supplier_sku:
            master_record = self.db["ground_truth"].find_one({"sku": supplier_sku})
            if master_record:
                master_record['_id'] = str(master_record['_id'])
                return [master_record] # Return the perfect match

        # 2. Fallback: If SKU doesn't match, do a quick name search (just in case)
        cursor = self.db["ground_truth"].find({"name": {"$regex": title[:3], "$options": "i"}}).limit(3)
        suggestions = list(cursor)
        for s in suggestions:
            s['_id'] = str(s['_id'])
        return suggestions

    def get_all_inventory(self):
        """Returns all records in the live inventory as a list of dicts."""
        cursor = self.collection.find().sort("sku", ASCENDING)
        inventory = []
        for item in cursor:
            item['_id'] = str(item['_id'])
            inventory.append(item)
        return inventory

    def merge_products(self, duplicate_id: str):
        sku = "Unknown"
        try:
            d_id = ObjectId(duplicate_id)
            
            # 1. Fetch the messy record
            dirty_record = self.collection.find_one({"_id": d_id})
            if not dirty_record: 
                return False, "Record already deleted or not found"

            sku = dirty_record.get('sku', "Unknown")
            
            # 2. Path-finding for Ground Truth
            json_path = "/app/data/ground_truth.json" if os.path.exists("/app/data/ground_truth.json") else "data/ground_truth.json"
            
            golden = None
            if os.path.exists(json_path):
                with open(json_path, 'r') as f:
                    data = json.load(f)
                    golden = next((item for item in data if item["sku"].strip() == sku.strip()), None)

            if not golden:
                print(f"❌ STOP: SKU {sku} not in JSON. Keeping dirty record.", flush=True)
                return False, f"SKU {sku} not found in Truth"

            # 3. Calculate Total Stock
            # Look for an ALREADY validated record with this SKU (excluding the current one)
            existing_clean = self.collection.find_one({
                "sku": sku, 
                "is_validated": True, 
                "_id": {"$ne": d_id} 
            })
            
            current_dirty_stock = dirty_record.get('stock', 0)
            clean_stock = existing_clean.get('stock', 0) if existing_clean else 0
            total_stock = clean_stock + current_dirty_stock

            # 4. UPSERT: Create/Update the Golden Record
            # We filter by SKU to ensure only ONE master record exists per SKU
            self.collection.update_one(
                {"sku": sku, "is_validated": True}, # Target the validated one if it exists
                {"$set": {
                    "name": golden['name'],
                    "category": golden.get('category', 'General'),
                    "price": golden.get('price'),
                    "stock": total_stock,
                    "is_validated": True
                }},
                upsert=True
            )

            # 5. RE-FETCH to find the "Survivor"
            golden_record = self.collection.find_one({"sku": sku, "is_validated": True})
            golden_id = golden_record["_id"] if golden_record else None

            # 6. DELETE the dirty record ONLY if it wasn't the one we just upgraded
            if golden_id and str(d_id) != str(golden_id):
                self.collection.delete_one({"_id": d_id})
                print(f"✅ SUCCESS: Consolidated {sku}. Deleted duplicate {d_id}.", flush=True)
            else:
                print(f"💎 PROTECTED: {sku} upgraded in-place. No deletion needed.", flush=True)

            return True, "Reconciliation Success"

        except Exception as e:
            print(f"🔥 CRITICAL ERROR: {str(e)}", flush=True)
            return False, str(e)
    #     1. Combines stock.
    #     2. Fetches 'Correct Name' from Ground Truth based on SKU.
    #     3. Deletes the duplicate.
    #     """
    #     try:
    #         # Convert strings from Agent to MongoDB ObjectIds
    #         p_id = ObjectId(primary_id)
    #         d_id = ObjectId(duplicate_id)

    #         dup_product = self.collection.find_one({"_id": d_id})
            
    #         if dup_product:
    #             stock_to_add = dup_product.get("stock", 0)
    #             # Update primary
    #             self.collection.update_one(
    #                 {"_id": p_id}, 
    #                 {"$inc": {"stock": stock_to_add}}
    #             )
    #             # Delete duplicate
    #             before = self.collection.count_documents({})
    #             result = self.collection.delete_one({"_id": d_id})
    #             after = self.collection.count_documents({})
    #             print(f"--- DB INTERNAL CHECK ---")
    #             print(f"Target ID to delete: {d_id}")
    #             print(f"Rows before: {before} | Rows after: {after}")
    #             print(f"Delete result: {result.deleted_count}")
    #             print(f"--------------------------")
    #             logger.info(f"✅ Deleted duplicate {duplicate_id}. Success!")
    #             return True
    #         else:
    #             logger.warning(f"⚠️ Could not find duplicate ID {duplicate_id}")
    #             return False
    #     except Exception as e:
    #         logger.error(f"❌ DB Error in merge: {e}")
    #         return False