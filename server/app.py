import logging
import argparse
import os
from fastapi import HTTPException
import uvicorn
from fastapi.responses import HTMLResponse
from openenv.core.env_server.http_server import create_app
from my_env_environment import InventoryDB

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("InventoryServer")
db_helper = InventoryDB()

# --- IMPORT LOGIC ---
try:
    from models import InventoryAction, InventoryObservation
    from my_env_environment import MyEnvironment
except (ModuleNotFoundError, ImportError):
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from models import InventoryAction, InventoryObservation
    from my_env_environment import MyEnvironment

# Initialize the OpenEnv FastAPI application
app = create_app(
    MyEnvironment,
    InventoryAction,
    InventoryObservation,
    env_name="inventory_manager",
    max_concurrent_envs=4,
)

# --- ADDED FOR HF SPACE AUTO-PING ---
@app.get("/health")
async def health_check():
    """Explicit endpoint for the automated ping."""
    return {"status": "healthy", "env": "inventory_manager"}

@app.get("/inventory")
async def get_all_inventory():
    try:
        records = db_helper.get_all_inventory()
        for record in records:
            if "_id" in record:
                record["_id"] = str(record["_id"])
        return {"records": records}
    except Exception as e:
        logger.error(f"❌ API Error fetching inventory: {e}")
        raise HTTPException(status_code=500, detail="Could not fetch live inventory.")

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <body style="font-family: sans-serif; padding: 40px; line-height: 1.6; background: #f4f7f6;">
        <h1 style="color: #2c3e50;">📦 Ecommerce Inventory Space</h1>
        <p><strong>Status:</strong> <span style="color: #27ae60;">ACTIVE</span></p>
        <hr>
        <h3>Evaluation Endpoints:</h3>
        <ul>
            <li><code>POST /reset</code> - Evaluator calls this first.</li>
            <li><code>POST /step</code> - Evaluator sends actions here.</li>
            <li><code>GET /health</code> - Automated ping check.</li>
        </ul>
    </body>
    """

def main(host: str = "0.0.0.0", port: int = 8000): 
    logger.info(f"🚀 Inventory Server starting at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    # HF Spaces passes the port via environment variables sometimes
    port = int(os.environ.get("PORT", 8000))
    main(host="0.0.0.0", port=port)