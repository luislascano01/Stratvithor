import json
import requests
import re  # New import for regex
from typing import List, Optional


class QuerySynthesizer:
    """
    A class for generating search queries from an incoming prompt,
    using a local or remote LLM API (e.g., OLLAMA).
    Also includes functionality to extract a company's stock ticker symbol
    given relevant text.
    """

    def __init__(self, llm_api_url: str):
        """
        :param llm_api_url: The endpoint of your LLM service (e.g. 'http://localhost:11434/api/chat').
        """
        self.llm_api_url = llm_api_url

    def _call_llm(self, system_message: str, user_prompt: str) -> Optional[str]:
        """
        Internal method responsible for making the actual HTTP request to the LLM.
        Waits for a complete response and ensures it's fully received.
        :param system_message: System instructions for the LLM.
        :param user_prompt: The main content of the request.
        :return: The complete text response from the LLM or None if something went wrong.
        """
        payload = {
            "model": "gemma2:27b",  # Ensure this is the correct model name
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False  # Ensure we wait for the full response
        }
        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(self.llm_api_url, headers=headers, json=payload, timeout=5000)
            response.raise_for_status()  # Raise an error for HTTP failures

            # Ensure response is completely received
            data = response.json()
            print("Raw LLM Response:", data)  # Debugging line, remove after confirming

            # OLLAMA returns response under 'message' -> 'content'
            if "message" in data and "content" in data["message"]:
                message_response = data["message"]["content"].strip()
                print("Message Response GSrch Query Synth:", message_response)

                # Extract JSON content from the markdown block

                pattern = re.compile(r'(?:```json\s*([\s\S]*?)\s*```|([\s\S]+))', re.DOTALL)

                json_match = pattern.search(message_response)
                if json_match:
                    # If group(1) matched, it's the triple-backtick version;
                    # otherwise, group(2) contains the entire text.
                    extracted_content = json_match.group(1) or json_match.group(2)
                    print("✅ QuerySynthesizer: Extracted JSON from LLM\n:", extracted_content+"\n")
                    return extracted_content
                else:
                    print("❌ QuerySynthesizer: No JSON formatting detected for search prompts; returning raw message.")
                    return message_response

            return None  # Return None if no valid response found

        except requests.exceptions.RequestException as e:
            print(f"Error calling LLM: {e}")
            return None

    def generate_search_prompts(self, incoming_prompt: str) -> List[str]:
        """
        Generates three recommended Google search queries based on a complex user prompt.
        :param incoming_prompt: The user's initial question or problem statement.
        :return: A list of three search prompts.
        """
        system_instructions = (
            "You are a helpful assistant that generates Google search prompts. "
            "The user has asked a complex question. You need to produce exactly "
            "six (6) distinct search queries that would help the user find relevant information."
            "Two (and only two) of those search prompts titles must contain: filetype:pdf\n\n"
            "IMPORTANT: Return your answer as valid JSON with the following structure:\n\n"
            "{\n"
            '  "search_prompts": [\n'
            '    "Prompt 1",\n'
            '    "Prompt 2",\n'
            '    "Prompt 3",\n'
            '    "Prompt 4",\n'
            '    "Prompt 5",\n'
            '    "Prompt 6"\n'
            "  ]\n"
            "}\n\n"
            "No additional keys should be present. Only return the JSON formatted response."
        )

        user_message = f"The user asked: '{incoming_prompt}'. Please propose six(6) different Google search queries."

        raw_response = self._call_llm(system_instructions, user_message)
        if not raw_response:
            print("Warning: LLM call failed; returning generic queries.")
            return [f"{incoming_prompt} (Query 1)",
                    f"{incoming_prompt} (Query 2)",
                    f"{incoming_prompt} (Query 3)"]

        try:
            data = json.loads(raw_response)
            search_prompts = data.get("search_prompts", [])
            search_prompts = [s.capitalize() for s in search_prompts]
            return search_prompts
        except json.JSONDecodeError:
            print("Warning: Could not decode LLM response as JSON.")
            return [f"{incoming_prompt} (Fallback Query 1)",
                    f"{incoming_prompt} (Fallback Query 2)",
                    f"{incoming_prompt} (Fallback Query 3)"]


if __name__ == "__main__":
    llama_api_url = "http://localhost:11434/api/chat"  # Example OLLAMA endpoint
    synthesizer = QuerySynthesizer(llm_api_url=llama_api_url)
    curr_company_name = "Meta"
    # Test: Generating search prompts
    complex_prompt = (
        f"I need information about the financial status of {curr_company_name}."
        f" I'm interested in their debt leverage ratio, plus the their liquidity,"
        f" also cashflow, in general, I'm interested in the internal financial "
        f"standing of the company. I'm looking for official formal information as I'm a Banking Lender building a credit report for lending decision."
    )

    prompts_list = synthesizer.generate_search_prompts(complex_prompt)
    print("Generated Search Prompts:")
    for idx, p in enumerate(prompts_list, start=1):
        print(f"{idx}. {p}")