---
title: Inventory Management AI Environment
emoji: 📦
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
app_port: 8000
base_path: /
tags:
  - openenv
  - ecommerce
  - ai-agents
  - fastapi
---

# 📦 Inventory Management Environment

An automated ecommerce inventory environment built for the OpenEnv framework. This system enables AI agents to manage a product lifecycle through three distinct phases:

1. **Migration**: Mapping raw CSV data to a structured MongoDB schema  
2. **Reconciliation**: Deterministic deduplication of SKU entries  
3. **Conversation**: Natural language updates for price and stock management  

---

## 🚀 Quick Start

### Setup Instructions

1. **Create Virtual Environment**
   ```bash
   # Create virtual environment
   python -m venv venv
   ```

2. **Activate Virtual Environment**
   ```bash
   # Activate your virtual environment
   venv\Scripts\activate  # On Windows
   # or
   source venv/bin/activate  # On Unix systems
   ```

4. **Install Dependencies**
   ```bash
   pip install openenv-core
   ```

5. **Setup Environment Variables**
   Create a `.env` file in the root directory with the following variables:
   ```env
   API_KEY=your_api_key_here
   MONGO_URI=mongodb://localhost:27017
   DB_NAME=your_database_name
   server_url=http://localhost:8000
   HF_TOKEN=your_huggingface_token_here
   API_BASE_URL=your_api_base_url_here
   MODEL_NAME=your_model_name_here
   ```

6. **Run Docker Containers**
   ```bash
   docker compose up -d
   ```

7. **Access Services**
   - Database UI: http://localhost:8081
   - Application: Run the agent loop script

8. **Run the Application**
   ```bash
   python -m client.agent_loop
   ```

### Using the Environment

The environment operates through three distinct phases. Here's how to use it programmatically:

```python
import os
from openai import OpenAI
from client.client_wrapper import InventoryEnv
from inference import get_llama_action
from models import InventoryAction, ActionType
from dotenv import load_dotenv

load_dotenv()

def run_inventory_session():
    # Initialize LLM client
    llm_client = OpenAI(
        base_url=os.getenv("API_BASE_URL"), 
        api_key=os.getenv("API_KEY")
    )
    
    # Connect to the OpenEnv Server
    with InventoryEnv(base_url=os.getenv("server_url")).sync() as env_client:
        
        # --- PHASE 1: AUTOMATIC MAPPING (CSV -> DB) ---
        step_result = env_client.reset() 
        obs = step_result.observation
        done = False
        while not done:
            # Use LLM to extract structured data from source text
            llm_json = get_llama_action(llm_client, obs.source_text, mode="MAPPING")
            action = InventoryAction(
                action_type=ActionType.MAP,
                sku=llm_json.get("sku"),
                metadata=llm_json.get("metadata")
            )
            
            step_result = env_client.step(action)
            obs = step_result.observation 
            done = step_result.done
            
        # --- PHASE 2: SERVER-SIDE RECONCILIATION ---
        live_records = env_client.get_full_inventory()
        for record in live_records:
            if not record.get('is_validated'):
                action = InventoryAction(
                    action_type=ActionType.MERGE,
                    sku=record.get('sku'),
                    duplicate_id=str(record.get('_id'))
                )
                step_result = env_client.step(action)
                
        # --- PHASE 3: CONVERSATIONAL UPDATES ---
        while True:
            chat_input = input("\nUser: ").strip()
            if chat_input.lower() in ['exit', 'quit']:
                break
                
            llm_json = get_llama_action(llm_client, chat_input, mode="UPDATE")
            update_action = InventoryAction(
                action_type=ActionType.UPDATE,
                sku=llm_json.get("sku"),
                metadata=llm_json.get("updates")
            )
            
            step_result = env_client.step(update_action)
            if step_result.reward > 0:
                print(f"SUCCESS: {step_result.observation.message}")
            else:
                print(f"REJECTED: {step_result.observation.message}")

if __name__ == "__main__":
    run_inventory_session()
```

**Key Components:**
- **`InventoryEnv`**: Client wrapper for connecting to the environment server
- **`get_llama_action()`**: LLM-powered action extraction from text
- **Three Phases**: Mapping (CSV import), Reconciliation (deduplication), Updates (conversational)
- **Action Types**: `MAP`, `MERGE`, `UPDATE` for different phases
- **Sync Context**: Use `.sync()` for synchronous operations


### Included Endpoints

- **Dashboard** → `/` (Real-time environment status)  
- **API Docs** → `/docs` (Swagger/OpenAPI UI)  
- **Health Check** → `/health` (Returns `200 OK`)  

---

## ⚙️ Environment Details

### 🧩 Action (`InventoryAction`)

- `action_type`: One of `MAP`, `MERGE`, `UPDATE`, or `SKIP`  
- `sku`: Unique identifier for the product  
- `metadata`: Dictionary containing `name`, `price`, and `stock`  
- `duplicate_id`: *(Phase 2 only)* MongoDB ID to merge  

---

### 🔍 Observation (`InventoryObservation`)

- `source_text`: Raw input (CSV row or user message)  
- `db_suggestions`: List of similar database entries  
- `message`: Feedback or error messages  
- `done`: Indicates end of current phase  

---

## 🧠 Advanced Usage

### Connecting to a Hosted Server

If the environment is already running (locally or on Hugging Face), connect without spawning a new container:

```python
from my_env import MyEnv

env = MyEnv(base_url="https://<your-space-url>.hf.space")

with env:
    obs = env.reset().observation
    print(f"Task for Agent: {obs.source_text}")
```


## 📁 Project Structure

```text
my_env/
├── README.md                     # Documentation and HF Metadata
├── openenv.yaml                  # Manifest for the OpenEnv CLI
├── pyproject.toml                # Python dependencies and build system
├── docker-compose.yml            # Docker services configuration
├── Dockerfile                    # Main Docker build file
├── models.py                     # Pydantic models for Actions/Observations
├── inference.py                  # LLM-driven agent logic
├── __init__.py                   # Package initialization
├── client/                       # Client-side code
│   ├── __init__.py
│   ├── agent_loop.py             # Main agent execution loop
│   └── client_wrapper.py         # Environment client wrapper
├── data/                         # Sample data and test files
│   ├── delivery_notifications.txt
│   ├── ground_truth.json
│   └── supplier_products.csv
└── server/                       # Server-side code
    ├── __init__.py
    ├── app.py                    # FastAPI server (Port 8000)
    ├── my_env_environment.py     # Core logic and validation
    ├── db_utils.py               # MongoDB helper functions
    ├── seed_db.py                # Database seeding utilities
    ├── validator.py              # Data validation logic
    ├── requirements.txt          # Server dependencies
    └── Dockerfile                # Server-specific Docker build
```

