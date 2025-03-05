# RequestMngrAPI.py

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

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip Middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    api_key = request.headers.get("X-API-Key")
    if api_key != "your-secure-api-key":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await call_next(request)

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

# ----- Query Report Status -----
@app.get("/report_status/{task_id}")
async def report_status(task_id: str):
    """
    Polling endpoint to get the current status and final report (if completed).
    """
    if task_id not in active_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "task_id": task_id,
        "status": active_tasks[task_id]["status"],
        "report": active_tasks[task_id]["report"]
    }

# ----- Real-Time Updates via WebSocket -----
@app.websocket("/ws/{task_id}")
async def websocket_task_updates(websocket: WebSocket, task_id: str):
    """
    A WebSocket endpoint that streams DAG node updates in real time
    for a particular 'task_id'.
    """
    if task_id not in active_tasks:
        # If you prefer, accept the connection, send an error, and then close
        await websocket.accept()
        await websocket.send_json({"error": "Invalid task_id"})
        await websocket.close()
        return

    # Get the integrator and thus the ResultsDAG
    integrator = active_tasks[task_id]["integrator"]
    results_dag = integrator.results_dag

    await websocket.accept()

    try:
        # Loop over the watch_updates() generator
        async for (node_id, node_data) in results_dag.watch_updates():
            # Optionally check if the task is still "in-progress" before sending
            await websocket.send_json({
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