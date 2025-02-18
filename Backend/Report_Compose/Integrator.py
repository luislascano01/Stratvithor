import json
import asyncio
import networkx as nx

from DataMolder import DataMolder
from PromptManager import PromptManager


class Integrator:
    def __init__(self, yaml_file_path, web_search_url):
        """
        Initializes the Integrator by loading prompts from a YAML file and setting up dependencies.
        Also instantiates a DataMolder.
        :param yaml_file_path: Path to the YAML file containing prompts.
        :param web_search_url: The URL for the Web_Search API.
        """
        self.prompt_manager = None
        self.load_prompts(yaml_file_path)
        # Assume that DataMolder can be instantiated without parameters.
        self.data_molder = DataMolder()
        # Store the web search URL for use in each query.
        self.web_search_url = web_search_url

    def load_prompts(self, yaml_file_path):
        """
        Loads the YAML file and initializes the PromptManager.
        :param yaml_file_path: Path to the YAML file.
        """
        import yaml
        with open(yaml_file_path, "r", encoding="utf-8") as file:
            prompts_data = yaml.safe_load(file)

        self.prompt_manager = PromptManager(yaml_file_path)  # PromptManager loads its own data

    async def generate_report(self, company_name, custom_topic_focuser):
        """
        Generates the report by processing each prompt (except the "initial") in the DAG.
        Each prompt is processed only when all its parent prompts have completed.
        For each prompt:
          - Combine parent's responses as context.
          - Web-query using a new DataQuerier (with previous messages including parent responses and current prompt text).
          - Use DataMolder to "intersect" (i.e. refine) the web response with the prompt text and parent context.
          - Store the intersection result.
        Finally, all processed prompts are merged into a single JSON-formatted report.

        :param company_name: The name of the company for which the report is generated.
        :param custom_topic_focuser: Additional context to steer the query or intersection process.
        :return: A JSON-formatted string representing the report.
        """
        # Dictionary to store each prompt's processed (intersection) response.
        processed_results = {}  # prompt_id -> intersection result

        # Dictionary to store asyncio.Tasks for each prompt.
        tasks = {}

        # Get the DAG from the prompt manager and compute a topological order.
        prompt_dag = self.prompt_manager.prompt_dag
        topo_order = list(nx.topological_sort(prompt_dag))

        # Define an asynchronous function to process a single prompt.
        async def process_prompt(prompt_id, parent_context):
            """
            For a given prompt, create a DataQuerier instance (using parent's responses as context)
            and process the prompt text.
            """
            # Retrieve the prompt object from the PromptManager.
            prompt_obj = self.prompt_manager.get_prompt_by_id(prompt_id)
            focus_message = prompt_obj["text"]

            # Build previous_messages: first the parent context (if any), then the current prompt text.
            previous_messages = []
            if parent_context:
                previous_messages.append(parent_context)
            previous_messages.append(focus_message)

            # Instantiate a new DataQuerier for this prompt.
            from DataQuerier import DataQuerier
            data_querier = DataQuerier(previous_messages, focus_message, self.web_search_url)
            await data_querier.query_and_process()
            raw_data = data_querier.get_processed_data()

            # Use DataMolder to intersect the web response with the prompt text and parent context.
            # (Assuming DataMolder.process_data can accept a parent_context and a custom_topic_focuser.)
            intersection = self.data_molder.process_data(raw_data, parent_context, custom_topic_focuser)
            return intersection

        # Process each prompt in topological order.
        # Note: We assume that the "initial" prompt (if any) is not queried.
        for prompt_id in topo_order:
            prompt_obj = self.prompt_manager.get_prompt_by_id(prompt_id)
            # Skip the "initial" prompt (by convention, checking its section_title).
            if prompt_obj["section_title"].lower() == "initial":
                # Optionally, store the initial prompt's text as a base context.
                processed_results[prompt_id] = prompt_obj["text"]
                continue

            # Retrieve parent prompt IDs (dependencies) for this prompt.
            parent_ids = self.prompt_manager.get_prompt_dependencies(prompt_id)
            # Wait for parent's processing to complete (if any) and combine their responses.
            parent_context = ""
            if parent_ids:
                # Ensure parent's tasks have completed.
                parent_results = [processed_results[parent_id] for parent_id in parent_ids]
                # Combine parent's results into a single context string.
                parent_context = "\n".join(json.dumps(r) for r in parent_results)

            # Schedule the processing of this prompt.
            tasks[prompt_id] = asyncio.create_task(process_prompt(prompt_id, parent_context))
            # Immediately await tasks for nodes that have no children or that block later ones.
            # (Since the DAG is topologically sorted, we know that by the time a child is processed,
            #  its parent's tasks will have completed.)
            processed_results[prompt_id] = await tasks[prompt_id]

        # Build the final report: use the section_title from each prompt as the key.
        sections = {}
        for prompt_id in topo_order:
            prompt_obj = self.prompt_manager.get_prompt_by_id(prompt_id)
            # Skip the "initial" prompt if you don't want it in the final report.
            if prompt_obj["section_title"].lower() == "initial":
                continue
            sections[prompt_obj["section_title"]] = processed_results[prompt_id]

        report_data = {
            "company": company_name,
            "sections": sections
        }
        return json.dumps(report_data, indent=4)