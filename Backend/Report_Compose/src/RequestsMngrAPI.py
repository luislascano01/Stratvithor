import uuid
import time
import logging
import asyncio

from fastapi import FastAPI, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
from typing import Dict

from Backend.Report_Compose.src.Integrator import Integrator

# ----- Setup FastAPI -----
app = FastAPI()

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip Middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ----- Data Model for requests -----
class ReportRequest(BaseModel):
    company_name: str
    mock: bool = False  # We can specify if we want to run in mock mode

# We'll store references to integrator objects or results by task_id
active_tasks: Dict[str, Dict] = {}  # task_id -> { "integrator": Integrator, "status": ..., "report": ... }

# ----- Health Check Endpoint -----
@app.get("/health")
async def health_check():
    return {"status": "running"}

# ----- Start Report Generation -----
@app.post("/generate_report")
async def generate_report(request: ReportRequest, background_tasks: BackgroundTasks):
    """
    Start generating a report in the background. Returns a task_id.
    """
    task_id = str(uuid.uuid4())
    # Create an Integrator with the YAML path
    integrator = Integrator(yaml_file_path="./Prompts/prompts.yaml")

    # Store in dictionary so we can reference it
    active_tasks[task_id] = {"integrator": integrator, "status": "in-progress", "report": None}

    # Kick off the background task
    background_tasks.add_task(run_report_task, task_id, request.company_name, request.mock)

    return {"task_id": task_id, "status": "Processing started"}

# The background task that calls Integrator
async def run_report_task(task_id: str, company_name: str, mock: bool):
    try:
        integrator = active_tasks[task_id]["integrator"]
        # Call the integrator's generate_report
        # This will fill the results in integrator.results_dag
        final_report_json = await integrator.generate_report(company_name, "", mock=mock)

        # Mark the task as complete
        active_tasks[task_id]["status"] = "completed"
        active_tasks[task_id]["report"] = final_report_json
    except Exception as e:
        active_tasks[task_id]["status"] = "failed"
        active_tasks[task_id]["report"] = str(e)

# ----- Real-Time Updates via WebSocket -----
@app.websocket("/ws/{task_id}")
async def websocket_task_updates(websocket: WebSocket, task_id: str):
    """
    A WebSocket endpoint that streams DAG node updates in real time
    for a particular 'task_id'. It first sends the full DAG structure.
    """
    if task_id not in active_tasks:
        await websocket.accept()
        await websocket.send_json({"error": "Invalid task_id"})
        await websocket.close()
        return

    # Get the integrator and thus the ResultsDAG and prompt_dag
    integrator = active_tasks[task_id]["integrator"]
    results_dag = integrator.results_dag
    dag = integrator.prompt_manager.prompt_dag

    # Build a simple DAG representation:
    dag_data = {
        "nodes": [
            {
                "id": node_id,
                "label": integrator.prompt_manager.get_prompt_by_id(node_id)["section_title"]
            }
            for node_id in dag.nodes()
        ],
        "links": [
            {"source": source, "target": target}
            for source, target in dag.edges()
        ]
    }

    await websocket.accept()

    # Send initial DAG structure message
    await websocket.send_json({"type": "init", "dag": dag_data})

    try:
        async for (node_id, node_data) in results_dag.watch_updates():
            await websocket.send_json({
                "type": "update",
                "task_id": task_id,
                "node_id": node_id,
                "status": node_data["status"],
                "result": node_data["result"]
            })
    except WebSocketDisconnect:
        logging.info(f"WebSocket disconnected for task_id={task_id}")

# ----------------------------------------------------------------------
#   MAIN ENTRY POINT to run the server on port 8181
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("RequestsMngrAPI:app", host="0.0.0.0", port=8181, reload=True)