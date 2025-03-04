import json
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

# Import the necessary classes.
# Adjust the import paths as needed for your project structure.
from Credentials.CredentialManager import CredentialManager
from Backend.Web_Search.src.SearchIntegrator import SearchIntegrator

# Initialize FastAPI app with detailed metadata.
app = FastAPI(
    title="SearchIntegrator API",
    version="1.0",
    description=(
        "This API integrates search functionality using various external search services. "
        "It accepts search parameters and credentials, and returns aggregated search results. "
        "Use the /health endpoint to check API status, and the /search endpoint to perform searches."
    ),
    docs_url="/docs",
    redoc_url="/redoc"
)


class SearchRequest(BaseModel):
    """
    Model representing the payload for a search request.

    Attributes:
        credentials: A JSON or YAML string containing API credentials.
        general_prompt: The general topic to search for.
        particular_prompt: A more specific prompt to refine the search.
        operating_path: Path where temporary files and outputs should be stored.
        llm_api_url: The endpoint URL of the LLM API to use for query synthesis.
        cse_id: Optional Custom Search Engine ID for filtering search results.
    """
    credentials: str = Field(..., description="A JSON or YAML string for credentials.")
    general_prompt: str = Field(..., description="General search prompt.")
    particular_prompt: str = Field(..., description="Particular search prompt.")
    operating_path: str = Field(..., description="Directory path for temporary file operations.")
    llm_api_url: str = Field(..., description="URL of the LLM API to use for query synthesis.")
    cse_id: Optional[str] = Field(None, description="Optional Custom Search Engine ID.")



@app.get("/")
def read_root():
    logging.info("👋 Root endpoint accessed.")
    return {"message": "Welcome to the SearchIntegrator API"}


@app.get(
    "/health",
    summary="API Health Check",
    description="Returns the health status of the API. Use this endpoint to verify that the API is up and running."
)
async def health_check():
    """
    Health Check Endpoint

    Returns:
        A JSON response with the status of the API.
    """
    logging.info("💓 Health check requested.")
    return {"status": "ok"}


class SearchAggregationResult(BaseModel):
    """
    Model representing an individual aggregated search result.

    Attributes:
        url: The URL of the search result.
        display_url: A shortened display version of the URL.
        snippet: A brief excerpt or summary of the result.
        title: The title of the search result.
        scrapped_text: The full text content extracted from the result.
        extension: The type of resource (e.g., 'html', 'pdf').
    """
    url: str = Field(..., description="The URL of the search result.")
    display_url: str = Field(..., description="A shortened display URL.")
    snippet: str = Field(..., description="A brief excerpt or summary of the result.")
    title: str = Field(..., description="The title of the search result.")
    scrapped_text: str = Field(..., description="The full text extracted from the search result.")
    extension: str = Field(..., description="The type of resource (e.g., 'html' or 'pdf').")


class SearchResponse(BaseModel):
    """
    Model representing the response for a search aggregation.

    Attributes:
        results: A list of aggregated search results.
    """
    results: List[SearchAggregationResult] = Field(..., description="List of aggregated search results.")

@app.post(
    "/search",
    summary="Search Aggregation",
    description=(
            """Accepts search parameters and credentials, performs an aggregated search using external search services, "
            "and returns the results."
            
**Credentials Format**  
The `credentials` field should be a YAML (or JSON) string containing your keys.  
For example:

```yaml
API_Keys:
  Google_Cloud: "YOUR_GOOGLE_CLOUD_KEY"
  OpenAI: "YOUR_OPENAI_KEY"

Online_Tool_ID:
  Custom_G_Search: "YOUR_CUSTOM_G_SEARCH_ID
  ```
  
  **Endpoint Behavior**\n
	- Validates and loads the credentials with CredentialManager.\n
	- Initializes SearchIntegrator with your prompts.\n
	- Aggregates search results from external sources.    
"""

    ), response_model=SearchResponse, status_code=200
)
async def search_endpoint(request: SearchRequest):
    """
    Search Endpoint

    This endpoint accepts a SearchRequest payload containing credentials and search parameters, initializes the
    CredentialManager and SearchIntegrator, and returns aggregated search results.

    - **credentials**: A JSON or YAML string for credentials.
    - **general_prompt**: A general search query.
    - **particular_prompt**: A specific search query to refine the general prompt.
    - **operating_path**: The path for file operations.
    - **llm_api_url**: The URL of the LLM API.
    - **cse_id**: Optional Custom Search Engine ID.

    Raises:
        HTTPException: If initialization of CredentialManager or SearchIntegrator fails, or if the search integration fails.

    Returns:
        A JSON object with the aggregated search results.

          ```json
  {
      "results": [
          {
              "url": "https://www.csis.org/analysis/assessing-viability-us-ukraine-minerals-deal",
              "display_url": "www.csis.org",
              "snippet": "Feb 21, 2025 ... U.S. President Donald Trump ...",
              "title": "Assessing the Viability of a U.S.-Ukraine Minerals Deal",
              "scrapped_text": "Critical Questions by Gracelin Baskaran ...",
              "extension": "html"
          },
          {
              "url": "https://www.defense.gov/Spotlights/Support-for-Ukraine/Timeline/",
              "display_url": "www.defense.gov",
              "snippet": "Jan 15, 2025 ... This international security assistance ...",
              "title": "Russian War in Ukraine: Timeline",
              "scrapped_text": "Timeline",
              "extension": "html"
          }
          // ... additional results ...
      ]
  }
  ```
    """
    logging.info("🔎 Received search request.")
    try:
        # Initialize CredentialManager using provided credentials.
        cred_manager = CredentialManager(request.credentials)
        logging.info("✅ CredentialManager loaded successfully.")
    except Exception as e:
        logging.error(f"❌ Failed to initialize CredentialManager: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid credentials provided: {e}")

    try:
        # Initialize SearchIntegrator with the search prompts and CredentialManager.
        integrator = SearchIntegrator(
            general_prompt=request.general_prompt,
            particular_prompt=request.particular_prompt,
            cred_mngr=cred_manager,
            operating_path=request.operating_path
        )
        logging.info("✅ SearchIntegrator initialized successfully.")
    except Exception as e:
        logging.error(f"❌ Failed to initialize SearchIntegrator: {e}")
        raise HTTPException(status_code=500, detail="Failed to initialize SearchIntegrator.")

    try:
        # Execute aggregated search and capture results.
        results = integrator.get_aggregated_response(request.llm_api_url, request.cse_id)
        logging.info("✅ Successfully aggregated search results.")
        print(json.dumps(results, indent=4))
    except Exception as e:
        logging.error(f"❌ Error during search integration: {e}")
        raise HTTPException(status_code=500, detail=f"Search integration failed: {e}")

    logging.info("🚀 Search request completed.")
    return {"results": results}


# If running this file directly, use Uvicorn to run the API.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8383)
