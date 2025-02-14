from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import BaseModel
import time
import logging
import uuid

from Integrator import Integrator


# Initialize FastAPI
app = FastAPI()

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# Store report statuses
report_status = {}

# Initialize dependencies
yaml_file = "./Prompts/prompts.yaml"
integrator = Integrator(yaml_file)

# CORS Middleware (Adjust allow_origins for security)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Response Compression Middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)


### Middleware for Logging Requests & Responses ###
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time

    logging.info(f"{request.method} {request.url} - {response.status_code} ({process_time:.2f}s)")
    return response


### Middleware for Simple Authentication (Optional) ###
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    api_key = request.headers.get("X-API-Key")
    if api_key != "your-secure-api-key":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await call_next(request)


### Data Model for Report Requests ###
class ReportRequest(BaseModel):
    company_name: str


### 1️⃣ Health Check Endpoint ###
@app.get("/health")
async def health_check():
    """
    Check if the service is running.
    """
    return {"status": "running"}


### 2️⃣ Report Generation Endpoint ###
@app.post("/generate_report")
async def generate_report(request: ReportRequest, background_tasks: BackgroundTasks):
    """
    Start the JSON report generation process in the background.
    Returns a task_id to track progress.
    """
    task_id = str(uuid.uuid4())  # Generate a unique task ID
    report_status[task_id] = "In Progress"

    # Run report generation in the background
    background_tasks.add_task(process_report, task_id, request.company_name)

    return {"task_id": task_id, "status": "Processing started"}


### 3️⃣ Report Status Endpoint ###
@app.get("/report_status/{task_id}")
async def report_status_check(task_id: str):
    """
    Check the progress of a report generation task.
    """
    status = report_status.get(task_id, "Not Found")
    if status == "Not Found":
        raise HTTPException(status_code=404, detail="Task ID not found")
    return {"task_id": task_id, "status": status}


### Background Task: Report Processing ###
def process_report(task_id: str, company_name: str):
    """
    Generates a report and stores the result under task_id.
    """
    try:
        report = integrator.generate_report(company_name)
        report_status[task_id] = {"status": "Completed", "report": report}
    except Exception as e:
        report_status[task_id] = {"status": "Failed", "error": str(e)}