import asyncio
import json
import logging
import os
import random
import tempfile
from typing import Dict
from xml.etree.ElementTree import indent

import networkx as nx
import yaml

from Backend.Report_Compose.src.DataMolder import DataMolder
from Backend.Report_Compose.src.DataQuerier import DataQuerier
from Backend.Report_Compose.src.ResultsDAG import ResultsDAG
from Backend.Report_Compose.src.PromptManager import PromptManager
import json
import httpx


def load_openai_api_key(yaml_file_path: str) -> str:
    """
    Loads the OpenAI API key from the given YAML file.
    Implements error handling for missing file, parsing errors, or missing key.
    """
    try:
        # Check if file exists
        if not os.path.exists(yaml_file_path):
            raise FileNotFoundError(f"YAML file not found: {yaml_file_path}")

        # Open and parse the YAML file
        with open(yaml_file_path, "r") as file:
            data = yaml.safe_load(file)

        # Validate if the OpenAI key exists
        if "API_Keys" not in data or "OpenAI" not in data["API_Keys"]:
            raise KeyError("OpenAI API key is missing from the YAML file.")

        return data["API_Keys"]["OpenAI"]

    except FileNotFoundError as e:
        print(f"Error: {e}")
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}")
    except KeyError as e:
        print(f"Error: {e}")
    return ""


class Integrator:
    """
    This class serves as a orchestrator of the services necessary to compose the report based on the YAML file.
    Integrator interacts with Prompt_Manager to store and retrieve the prompts from a YAML file.

    Although composing the report could all be done in one shot, since the time it would take to complete the report
    by the LLM on the back-end are at the moment too long. It is important that each completed prompt node
    is returned as we complete the prompt. The idea is that Integrator interacts with RequestMngrAPI who is
    responsible for handling the incoming report generation request that are coming from the front-end.

    The YAML prompt file contains the prompts (section_name, text, id, system) and the prompt_dag which corresponds
    to a graph indicating how prompts depend on each other. Although PromptManager takes care of the Directed-Acyclic
    Graph, the prompts need to be explored by Integrator in topological order such that the parents prompt results
    are added to the context of the corresponding child prompts.

    The dag needs to be explored asynchronously per each node, and once any non-system (system = false)
     node DataQuery data is retrieved, then such output needs to be sent to DataMolder which will accept all the
     previous context and responses (in consecutive order) plus the results of the Web Search done by the corresponding
     Data Querier node.

     The result output from Data Molder (which is a LLM-based program) then becomes the current node's output.

     As the Directed-Acyclic-Graph gets completed; the results for each node should be placed on DAG structure
     in our case we will have a separated file: ResultsDAG.py which gets updated every time a node is completed.

    A great approach would be to BFS the prompts inside PromptManager and every time some node gets completed; store it
    in a node inside the ResultsDAG object.

    Ultimately, the ResultsDAG object should be accessible through our front-end-facing class "RequestMngrAPI.py"
    that will be the instantiator of all the process. Such API will have a WebSocket with the front-end (client)
    so that the client PC is able to explore the resulting information.


    """

    def __init__(self, yaml_file_path: str):
        """
        Initialize the Integrator with a path to the prompts YAML.
        Creates a PromptManager and a fresh ResultsDAG.
        """
        self.yaml_file_path = yaml_file_path  # <-- Add this line to store the file path
        self.prompt_manager = PromptManager(yaml_file_path)
        self.results_dag = ResultsDAG()
        self.tasks = {}
        self.openAI_API_key = load_openai_api_key("./Credentials/Credentials.yaml")
        self.focus_message = "Default Focus Message"
        self.web_search = True

    async def get_search_api_url(self):
        # List candidate base URLs in order of preference.
        candidates = ["http://localhost:8383", "http://web_search_api:8383"]
        async with httpx.AsyncClient() as client:
            for base_url in candidates:
                health_url = f"{base_url}/health"
                try:
                    response = await client.get(health_url, timeout=2.0)
                    if response.status_code == 200 and response.json().get("status") == "ok":
                        # Return the /search endpoint URL for the healthy candidate.
                        return f"{base_url}/search"
                except Exception as e:
                    print(f"Health check failed for {base_url}: {e}")
        raise Exception("No available Search API endpoint.")

    async def process_node(self, node_id: int, focus_message) -> tuple[None, None] | tuple[str, any]:
        curr_prompt = self.prompt_manager.get_prompt_by_id(node_id)

        if curr_prompt['system'] is True:
            logging.info(f"Skipping node {node_id} since it's system prompt")
            return "**This is a system prompt**", {"results": [{"System Node": "NA_system_node"}]}

        if self.web_search:
            # Dynamically determine the Search API URL.
            search_api_url = await self.get_search_api_url()
            querier = DataQuerier(curr_prompt['text'], focus_message, search_api_url)
            print(f'Processing node {node_id} with prompt: {json.dumps(curr_prompt, indent=4)}')
            await querier.query_and_process()
            online_data = querier.get_processed_data()
        else:
            online_data = {"results": [{"mock_data": "place_holder"}]}
        print(f'Count of articles found for node {node_id}: {len(online_data)}')

        molder = DataMolder("gpt-4o", self.openAI_API_key)
        ancestor_messages = self.get_ancestor_chat_hist(node_id)
        response = await molder.process_data(online_data, ancestor_messages, focus_message)
        return response, online_data

    def get_ancestor_chat_hist(self, node_id: int) -> list[Dict[str, any]]:
        """
        This method is necessary for building the chat history so far at a current node
        so only the relevant chat history is later sent to be processed by the LLM.
        How it works is that given the results_dag data-structure; the method references
        the correct node by ID then backtraces to root node.
        Then from 0 (current node) it retrieves both the response of the node and the
        prompt for such node. Is important to note that the retrieval is done by querying
        the PromptManager and ResultsDAG correspondingly.
        Since the ResultsDAG contains responses from the LLM, while the PromptManager contains the
        messages sent to the LLM (from user or system), then this is necessary to inform leveraging
        the Dictionary. Some nodes may not contain an LLM response from the RAG.
        :param node_id: ID of the node to retrieve the chat history for.
        :return: A list of the chat history for the given node.
                Example:
                    [{entity: 'system',
                      text: 'system_prompt',
                      },
                     {entity: 'user',
                      text: 'user prompt',
                    },
                     {entity: 'llm',
                     text: 'llm response'
                     }
                    ]
                The system prompts will not be followed by responses from the LLM.
        """
        dag = self.prompt_manager.prompt_dag

        # 1. Collect all ancestors of 'node_id', plus the node itself
        ancestors = nx.ancestors(dag, node_id)

        relevant_nodes = ancestors.union({node_id})

        # 2. Perform a topological sort of the entire DAG
        full_order = list(nx.topological_sort(dag))

        # 3. Filter to only those that lead to 'node_id'
        path_nodes = [n for n in full_order if n in relevant_nodes]

        chat_history = []

        for n in path_nodes:
            prompt = self.prompt_manager.get_prompt_by_id(n)
            if not prompt:
                # Should never happen if the YAML is valid, but just in case
                continue

            # 4a. Add the node's own prompt (system => "system", else => "user")
            if prompt["system"]:
                chat_history.append({
                    "entity": "system",
                    "text": prompt["text"]
                })
            else:
                chat_history.append({
                    "entity": "user",
                    "text": prompt["text"]
                })

            # 4b. If there's a completed LLM response, add it (optional business logic)
            node_result = self.results_dag.get_result(n)
            if node_result and node_result["status"] == "complete":
                # By default, we only add LLM response for non-system prompts,
                # but adjust if your logic differs.
                if not prompt["system"]:
                    chat_history.append({
                        "entity": "llm",
                        "text": str(node_result["result"]['llm'])  # Using llm here is very important to avoid
                        # input overflow of ancestor online_data
                    })

        return chat_history

    async def queue_node(self, node_id: int, dag: nx.DiGraph, mock: bool):
        """
        Process a single node in the DAG. This task will:
          1. Wait for all parent node tasks to complete.
          2. Run the node's processing (mock or real).
          3. Store the result or mark failure.
        """
        parent_ids = list(dag.predecessors(node_id))
        if parent_ids:
            await asyncio.gather(*(self.tasks[parent_id] for parent_id in parent_ids))

        try:
            # <--- 1) Mark the node as processing right here
            self.results_dag.mark_processing(node_id, "Node is currently being explored")
            result = {}
            node_prompt = self.prompt_manager.get_prompt_by_id(node_id)
            node_name = node_prompt["section_title"]
            if mock:
                # Simulate processing
                process_time = abs(random.gauss(5, 2))
                await asyncio.sleep(process_time)
                result = {'llm': "Some llm response", "online_data": "some_online_data"}
            else:
                # IMPORTANT: Await the async call to process_node so that you store the final result.
                response, online_data = await self.process_node(node_id, self.focus_message)
                result = {'llm': response, 'online_data': online_data}
            result['section_tile'] = node_name
            self.results_dag.store_result(node_id, result)
        except Exception as e:
            self.results_dag.mark_failed(node_id, str(e))

    async def generate_report(self, focus_message: str, mock: bool = False, web_search: bool = True) -> str:
        """
        Process the prompt DAG concurrently.
        Each node is scheduled as soon as its dependencies are complete.
        The web_search flag is set based on the API parameter.
        """
        self.focus_message = focus_message
        self.web_search = web_search  # Propagate the parameter to the integrator

        dag = self.prompt_manager.prompt_dag

        # Initialize each node in ResultsDAG as "pending"
        for node_id in dag.nodes():
            self.results_dag.init_node(node_id)

        # Schedule tasks for each node in topological order
        for node_id in nx.topological_sort(dag):
            self.tasks[node_id] = asyncio.create_task(self.queue_node(node_id, dag, mock))

        # Await all node tasks concurrently
        await asyncio.gather(*self.tasks.values())

        print(json.dumps(self.results_dag.to_json(), indent=4))
        return self.results_dag.to_json()

    ##############################
    ##############################
    # Updated DOCX generation using pypandoc

    def generate_docx_report(self, llm_format: str = "Markdown") -> str:
        """
        Generates a DOCX report using the final DAG results.
        """
        try:
            dag_obj = json.loads(self.results_dag.to_json())
        except Exception as e:
            raise Exception(f"Error parsing DAG data: {e}")

        dag_graph = self.prompt_manager.prompt_dag
        node_order = list(nx.topological_sort(dag_graph))

        prompt_set = os.path.basename(self.yaml_file_path).replace(".yaml", "")

        if llm_format.lower() == "markdown":
            return self.generate_docx_from_md(dag_obj, node_order, prompt_set)
        else:
            raise Exception(f"Unsupported llm_format: {llm_format}. Only 'Markdown' is currently supported.")

    def generate_docx_from_md(self, dag_obj: dict, node_order: list, prompt_set: str) -> str:
        """
        Helper method that generates a DOCX report from Markdown-formatted LLM responses.
        This version builds a complete Markdown string for the report and then uses pypandoc to
        convert it into a DOCX file. Note that any headings inside the LLM response are shifted down one
        level (e.g., a '#' becomes '##') so that the main section heading (already level 1) remains distinct.
        """
        import pypandoc

        def adjust_markdown_heading(md_text: str) -> str:
            """Prefix markdown headings with an extra '#' to shift their level."""
            adjusted_lines = []
            for line in md_text.splitlines():
                if line.lstrip().startswith("#"):
                    adjusted_lines.append("#" + line)
                else:
                    adjusted_lines.append(line)
            return "\n".join(adjusted_lines)

        # Build the report as a single Markdown string.
        report_md = f"# Aggregated Report\n\n"
        report_md += f"**Prompt Set:** {prompt_set}\n\n"
        report_md += f"**Focus Message:** {self.focus_message}\n\n"

        # Main report sections.
        for idx, node_id in enumerate(node_order, start=1):
            node_result = dag_obj.get(str(node_id)) or dag_obj.get(node_id)
            if not node_result:
                continue
            section_title = (node_result.get("result", {}).get("section_tile") or
                             node_result.get("result", {}).get("section_title"))
            llm_response = node_result.get("result", {}).get("llm", "No LLM response found.")

            # Adjust any headings in the LLM response.
            adjusted_llm_response = adjust_markdown_heading(llm_response)
            report_md += f"## {idx}. {section_title}\n\n"
            report_md += f"{adjusted_llm_response}\n\n"

        # Appendix for online data.
        report_md += "# Appendix: Online Data\n\n"
        for idx, node_id in enumerate(node_order, start=1):
            node_result = dag_obj.get(str(node_id)) or dag_obj.get(node_id)
            if not node_result:
                continue
            online_data = node_result.get("result", {}).get("online_data", "No online data found.")
            section_title = (node_result.get("result", {}).get("section_tile") or
                             node_result.get("result", {}).get("section_title") or
                             f"Section {idx}")
            report_md += f"## Section {idx} Online Data - {section_title}\n\n"
            report_md += f"{str(online_data)}\n\n"

        # Convert the markdown string to DOCX using pypandoc.
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
        tmp_file.close()  # Close the file so pypandoc can write to it.
        pypandoc.convert_text(report_md, to='docx', format='md', outputfile=tmp_file.name)
        return tmp_file.name

    def generate_pdf_report(self) -> str:
        """
        Generates a PDF report using the final DAG results by first creating a DOCX report
        and then converting it to PDF.
        """
        docx_path = self.generate_docx_report()
        try:
            from docx2pdf import convert
        except ImportError:
            raise Exception("docx2pdf module is required for PDF conversion. Please install it.")

        pdf_tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        pdf_tmp_file.close()

        try:
            convert(docx_path, pdf_tmp_file.name)
        except Exception as e:
            raise Exception(f"Error converting DOCX to PDF: {e}")

        return pdf_tmp_file.name