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

The simplest way to use the environment is through the `MyEnv` class:

```python
from my_env import InventoryAction, MyEnv
import asyncio

async def run_example():
    # Create environment from your local Docker image
    env = MyEnv.from_docker_image("inventory_agent_v1:latest")

    try:
        # Reset: Wipes DB and begins Phase 1 (CSV Migration)
        result = env.reset()
        print(f"Status: {result.observation.message}")

        # Step: Map a specific SKU from the source text
        action = InventoryAction(
            action_type="MAP", 
            sku="APL-IP15-P", 
            metadata={"name": "iPhone 15 Pro", "price": 999.0, "stock": 10}
        )
        
        result = env.step(action)
        print(f"Feedback: {result.observation.message}")
        print(f"Current Reward: {result.reward}")

    finally:
        # Always clean up the container session
        env.close()

if __name__ == "__main__":
    asyncio.run(run_example())
```
## 🐳 Building the Docker Image

Before deploying to Hugging Face or running locally, build the production image:

```bash
# From project root
docker build -t inventory_agent_v1:latest -f server/Dockerfile .
```
## 🤗 Deploying to Hugging Face Spaces

This environment is fully compatible with Hugging Face Docker Spaces.

### Using the OpenEnv CLI

```bash
# Push to your namespace
openenv push --app-port 8000
```
### Manual Deployment

1. Create a new Docker Space on Hugging Face  
2. Ensure `app_port: 8000` is set in the README metadata  
3. Add your `GROQ_API_KEY` or `HF_TOKEN` as Secrets in Space settings  

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
## 🧪 Development Testing

To verify environment logic without HTTP overhead:

```bash
python3 server/my_env_environment.py
```
## 📁 Project Structure

```text
my_env/
├── README.md              # Documentation and HF Metadata
├── openenv.yaml           # Manifest for the OpenEnv CLI
├── pyproject.toml         # Python dependencies and build system
├── models.py              # Pydantic models for Actions/Observations
├── inference.py           # LLM-driven agent logic
└── server/
    ├── app.py                 # FastAPI server (Port 8000)
    ├── my_env_environment.py  # Core logic and validation
    ├── db_utils.py            # MongoDB helper functions
    └── Dockerfile             # Multi-stage build
```

venv??
pip install openenv-core
.env
run docker

localhost8081 db

if want to run on local
docker compose command
python -m server.app
python -m client.agent_loop

why is reward 1 and =0.5 when running agent_loop   prev docker cont running
fix merging logic
done variable??
ctegory not coming after map
removee seed_db????
what the hell are those functions in clientwrapper