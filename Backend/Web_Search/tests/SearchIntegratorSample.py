from pathlib import Path
import logging

# Import your classes (adjust the import paths as needed)
from Backend.Web_Search.src.SearchIntegrator import SearchIntegrator
from Credentials.CredentialManager import CredentialManager

def format_resource(resource: dict) -> str:
    """
    Formats a resource dictionary into a pretty ASCII string.
    """
    separator = "=" * 80
    sub_separator = "-" * 80

    title = resource.get("title", "N/A")
    url = resource.get("url", "N/A")
    display_url = resource.get("display_url", "N/A")
    snippet = resource.get("snippet", "N/A")
    extension = resource.get("extension", "N/A")
    scrapped_text = resource.get("scrapped_text", "N/A")

    formatted = (
        f"{separator}\n"
        f"Title      : {title}\n"
        f"URL        : {url}\n"
        f"Display URL: {display_url}\n"
        f"Snippet    : {snippet}\n"
        f"Extension  : {extension}\n"
        f"{sub_separator}\n"
        f"Scrapped Text:\n{scrapped_text}\n"
        f"{separator}\n"
    )
    return formatted

def main():
    # Set up logging (if not already set globally)
    logging.basicConfig(level=logging.INFO)

    # Define the Llama URL (for the LLM API)
    llama_url = "http://localhost:11434/api/chat"

    # Set up a CredentialManager.
    # (Assuming you have a credentials.yaml file with appropriate keys.)

    # Assuming CredentialManager is defined/imported in your project.

    llama_url = "http://localhost:11434/api/chat"

    # Set up a CredentialManager with a relative path from the project's base directory.
    cred_mngr = CredentialManager("./Credentials/Credentials.yaml")

    # Define an operating directory (where any output files will be stored)
    operating_path = "./output"

    # Instantiate the SearchIntegrator with your prompts and credentials.
    search_integrator = SearchIntegrator(
        general_prompt="Ukraine and Russia War",
        particular_prompt="Zelensky in White House",
        cred_mngr=cred_mngr,
        operating_path=operating_path
    )

    # Get the aggregated response (this method returns a List[Dict[str, object]])
    aggregated_response = search_integrator.get_aggregated_response(llm_api_url=llama_url)

    # Print out the aggregated response in a formatted manner.
    print("Aggregated Response:")
    for resource in aggregated_response:
        print(format_resource(resource))

if __name__ == "__main__":
    main()