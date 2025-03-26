import os
import pickle
import uuid
import time
import logging
import asyncio
import json  # for JSON handling
import tempfile
from docx import Document
from fastapi import FastAPI, BackgroundTasks, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
PROMPTS_DIR = "./Prompts"

# GZip Middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Hardcoded list of available download formats.
AVAILABLE_DOWNLOAD_FORMATS = ["docx", "pdf"]


class PromptUpdateRequest(BaseModel):
    yaml_file_path: str


global map_name_to_file


@app.get("/get_prompts")
async def get_prompts():
    """Fetch all available prompt sets and map names to file paths."""
    try:
        logging.info(f'Prompt Directory: {PROMPTS_DIR}')
        prompt_files = [f for f in os.listdir(PROMPTS_DIR) if f.endswith(".yaml")]

        # Populate the map (remove file extension for cleaner names)
        global map_name_to_file
        map_name_to_file = {
            f.replace(".yaml", ""): os.path.join(PROMPTS_DIR, f) for f in prompt_files
        }

        return list(map_name_to_file.keys())  # Return clean names for frontend
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/update_prompt")
async def update_prompt(request: PromptUpdateRequest):
    """Update the selected prompt set."""
    global yaml_file_path
    yaml_file_path = os.path.join(PROMPTS_DIR, request.yaml_file_path)
    return {"message": "Prompt set updated", "new_path": yaml_file_path}


# We'll store references to integrator objects or results by task_id
active_tasks: Dict[str, Dict] = {}  # task_id -> { "integrator": Integrator, "status": ..., "report": ... }

# Define the persistent volume path (mounted in Docker to "./Backend/Z_Req_data")
STORAGE_DIR = "./Backend/Z_Req_data"

# Ensure the storage directory exists
os.makedirs(STORAGE_DIR, exist_ok=True)


# Updated /save_task_result endpoint with metadata
@app.post("/save_task_result/{task_id}")
async def save_task_result(task_id: str):
    """
    Saves the final report result (DAG + node data) along with metadata:
      - prompt set name
      - focus prompt text
      - processed_online flag
      - saved_at timestamp
    and saves the prompt set (YAML file) to disk.
    """
    logging.info('save_task_result endpoint called with task_id: %s', task_id)
    # Verify the task exists
    if task_id not in active_tasks:
        raise HTTPException(status_code=404, detail="Task not found.")
    logging.info('Task %s found in active_tasks', task_id)

    task = active_tasks[task_id]

    # Check if the task is completed; if not, return an error.
    if task["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail="Task is still executing. Please wait until it completes before saving."
        )
    logging.info('Task %s is completed. Proceeding to save report and prompt set.', task_id)

    # Define filenames for the report and prompt set
    report_file = os.path.join(STORAGE_DIR, f"{task_id}.json")
    prompt_file = os.path.join(STORAGE_DIR, f"{task_id}_prompt.yaml")

    # Build metadata
    integrator = task["integrator"]
    # Extract prompt set name from YAML file path (e.g., "MyPrompt" from "./Prompts/MyPrompt.yaml")
    prompt_set = os.path.basename(integrator.yaml_file_path).replace(".yaml", "")
    focus_message = integrator.focus_message
    # Assume the integrator stores the online flag as an attribute; default to False if not present
    processed_online = getattr(integrator, "web_search", False)
    saved_at = time.strftime("%Y-%m-%d %H:%M:%S")
    metadata = {
        "prompt_set": prompt_set,
        "focus_message": focus_message,
        "processed_online": processed_online,
        "saved_at": saved_at
    }

    # Combine final report and metadata into one JSON object
    dag_str = integrator.results_dag.to_json()  # This is likely a JSON string
    dag_obj = json.loads(dag_str)  # Convert string -> Python dict

    dag_graph = {
        "nodes": [
            {
                "id": node_id,
                "label": integrator.prompt_manager.get_prompt_by_id(node_id)["section_title"]
            }
            for node_id in integrator.prompt_manager.prompt_dag.nodes()
        ],
        "links": [
            {"source": s, "target": t}
            for s, t in integrator.prompt_manager.prompt_dag.edges()
        ]
    }

    final_data = {
        "report": task["report"],
        "dag": dag_obj,  # This is the dictionary of node => {status, result}
        "graph": dag_graph,  # The shape your front end needs for initGraph()
        "metadata": metadata
    }

    # Save the final report result with metadata
    logging.info('Saving final report to %s', report_file)
    try:
        with open(report_file, "w") as rf:
            rf.write(json.dumps(final_data, indent=4))
            logging.info('Final report successfully saved to %s', report_file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving report: {e}")

    # Save the prompt set that was used for this task.
    logging.info('Saving prompt set from %s to %s', integrator.yaml_file_path, prompt_file)
    try:
        with open(integrator.yaml_file_path, "r") as pf:
            prompt_content = pf.read()
        with open(prompt_file, "w") as pf_out:
            pf_out.write(prompt_content)
            logging.info('Prompt set successfully saved to %s', prompt_file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving prompt set: {e}")

    # ... (existing code that saves report_file and prompt_file)

    # Save the Integrator object using pickle
    integrator_file = os.path.join(STORAGE_DIR, f"{task_id}_integrator.pkl")
    logging.info('Saving Integrator object to %s', integrator_file)
    try:
        with open(integrator_file, "wb") as f:
            pickle.dump(integrator, f)
            logging.info('Integrator object successfully saved to %s', integrator_file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving Integrator object: {e}")

    logging.info('Task result saved successfully for task_id: %s', task_id)
    return {
        "message": "Task result saved successfully.",
        "report_file": report_file,
        "prompt_file": prompt_file,
        "metadata": metadata
        # Optionally, you can also include the path of the integrator file if needed:
        # "integrator_file": integrator_file
    }


# Updated GET endpoint to load saved data along with metadata

@app.get("/get_saved_task/{task_id}")
async def get_saved_task(task_id: str):
    """
    Retrieves a saved task result including:
      - The report and its metadata,
      - The prompt set.
    Also, loads the saved Integrator object to reinitialize the session.
    """
    report_file = os.path.join(STORAGE_DIR, f"{task_id}.json")
    prompt_file = os.path.join(STORAGE_DIR, f"{task_id}_prompt.yaml")
    integrator_file = os.path.join(STORAGE_DIR, f"{task_id}_integrator.pkl")

    if not os.path.exists(report_file) or not os.path.exists(prompt_file):
        raise HTTPException(status_code=404, detail="Saved task not found.")

    try:
        with open(report_file, "r") as rf:
            report_data = json.load(rf)
        with open(prompt_file, "r") as pf:
            prompt_content = pf.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading saved files: {e}")

    # Attempt to load the pickled Integrator object.
    if os.path.exists(integrator_file):
        try:
            with open(integrator_file, "rb") as f:
                integrator = pickle.load(f)
            # Reinitialize the active task session with the loaded integrator.
            active_tasks[task_id] = {
                "integrator": integrator,
                "status": "completed",
                "report": report_data.get("report")
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error loading Integrator object: {e}")
    else:
        # Optionally, you could choose to notify that no integrator was saved.
        raise HTTPException(status_code=404, detail="Saved Integrator object not found.")

    return {
        "task_id": task_id,
        "report_data": report_data,
        "prompt_set": prompt_content
    }


# ----- Health Check Endpoint -----
@app.get("/health")
async def health_check():
    return {"status": "running"}


# ----- New Endpoint: Download Options -----
@app.get("/download_options")
async def download_options():
    """
    Returns a list of available download formats.
    """
    return {"available_options": AVAILABLE_DOWNLOAD_FORMATS}


# ----- Start Report Generation -----

# Data Model for requests
class ReportRequest(BaseModel):
    company_name: str
    mock: bool = False
    prompt_name: str
    web_search: bool  # New toggle parameter


@app.post("/generate_report")
async def generate_report(request: ReportRequest, background_tasks: BackgroundTasks):
    """
    Start generating a report in the background. Returns a task_id.
    """
    prompt_name = request.prompt_name
    company_name = request.company_name
    logging.info(f"Generating report with focus prompt: {company_name}")

    # Validate prompt exists
    if prompt_name not in map_name_to_file:
        raise HTTPException(status_code=400, detail=f"Invalid prompt name: {prompt_name}")

    prompt_path = map_name_to_file[prompt_name]
    task_id = str(uuid.uuid4())

    # Create an Integrator with the YAML path
    integrator = Integrator(yaml_file_path=prompt_path)
    active_tasks[task_id] = {"integrator": integrator, "status": "in-progress", "report": None}

    # Pass the web_search toggle to the background task
    background_tasks.add_task(run_report_task, task_id, company_name, request.mock, request.web_search)

    return {"task_id": task_id, "status": "Processing started"}


async def run_report_task(task_id: str, company_name: str, mock: bool, web_search: bool):
    try:
        integrator = active_tasks[task_id]["integrator"]
        final_report_json = await integrator.generate_report(company_name, mock=mock, web_search=web_search)
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

    integrator = active_tasks[task_id]["integrator"]
    results_dag = integrator.results_dag
    dag = integrator.prompt_manager.prompt_dag

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


@app.get("/download_report/{task_id}")
async def download_report(task_id: str, file_type: str = "docx"):
    """
    Download the final report for a completed task.
    The 'file_type' query parameter determines which format to generate.
    """
    # Verify that the task exists.
    if task_id not in active_tasks:
        raise HTTPException(status_code=404, detail="Task not found.")

    task = active_tasks[task_id]
    # Ensure the task is completed.
    if task["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail="Task is still executing. Please wait until it completes before downloading the report."
        )

    integrator = task["integrator"]

    if file_type.lower() == "docx":
        try:
            report_path = integrator.generate_docx_report()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error generating DOCX report: {e}")
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif file_type.lower() == "pdf":
        try:
            report_path = integrator.generate_pdf_report()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error generating PDF report: {e}")
        media_type = "application/pdf"
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    return FileResponse(
        report_path,
        media_type=media_type,
        filename=f"{task_id}.{file_type.lower()}"
    )


# ----------------------------------------------------------------------
#   MAIN ENTRY POINT to run the server on port 8181
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("RequestsMngrAPI:app", host="0.0.0.0", port=8181, reload=True)
