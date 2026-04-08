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
        """The Agent calls this to 'Map' a dirty row into the clean schema."""
        clean_mapped_record = {
            "sku": sku,                                  # Master SKU from Agent
            "name": metadata.get("name", "Unknown"),    # Mapping 'title' -> 'name'
            "category": metadata.get("category", "N/A"), # Agent infers category
            "price": float(metadata.get("price", 0.0)),
            "stock": int(metadata.get("stock", 0)),
            "is_validated": False                         # A flag to show it hasn't been merged/verified yet
        }
        # Insert the cleaned record into the live inventory
        logger.info(f"Attempting to add product to DB: {clean_mapped_record}")
        return self.collection.insert_one(clean_mapped_record)
        # return self.collection.update_one(
        #     {"sku": sku}, 
        #     {"$set": clean_mapped_record}, 
        #     upsert=True
        # )
    def update_product(self, sku, updates: dict):
        """
        Updates specific fields for a validated record.
        'updates' can contain 'price', 'stock', or both.
        """
        if not sku:
            return False, "No SKU provided for update."

        # Perform the update in the Live Inventory
        result = self.collection.update_one(
            {"sku": sku, "is_validated": True},
            {"$set": updates}
        )
        
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
        """
        Deterministic Reconciler:
        1. Finds the messy record by ID.
        2. Finds the corresponding 'Golden Record' in Ground Truth by SKU.
        3. Merges data and sums stock in the Live Inventory.
        """
        from bson import ObjectId
        try:
            d_id = ObjectId(duplicate_id)
            
            # 1. Fetch the 'Dirty' record we just added from CSV
            dirty_record = self.collection.find_one({"_id": d_id})
            if not dirty_record:
                return False, "Record not found in Live Inventory."

            sku = dirty_record.get('sku')
            
            # 2. INTERNAL DB CALL: Find the 'Golden' version in Ground Truth
            golden = self.db["ground_truth"].find_one({"sku": sku})
            if not golden:
                return False, f"SKU {sku} not found in Master Catalog (Ground Truth)."

            # 3. Check if a 'Clean' version already exists in our Live DB
            # If it does, we add to its stock. If not, we create it.
            existing_clean = self.collection.find_one({"sku": sku, "is_validated": True})
            
            current_stock = dirty_record.get('stock', 0)
            base_stock = existing_clean.get('stock', 0) if existing_clean else 0
            total_stock = base_stock + current_stock

            # 4. UPSERT: Save the Golden Record to Live Inventory
            self.collection.update_one(
                {"sku": sku, "is_validated": True},
                {"$set": {
                    "name": golden['name'],
                    "category": golden.get('category'),
                    "price": golden.get('price'),
                    "stock": total_stock,
                    "is_validated": True
                }},
                upsert=True
            )

            # 5. DELETE: Remove the messy record (unless it was already the clean one)
            if not existing_clean or str(existing_clean['_id']) != str(d_id):
                self.collection.delete_one({"_id": d_id})
            
            return True, f"Successfully reconciled SKU {sku}. Total Stock: {total_stock}"

        except Exception as e:
            return False, str(e)
    # def merge_products(self, primary_id, duplicate_id):
    #     """
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