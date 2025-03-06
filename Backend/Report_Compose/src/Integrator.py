import asyncio
import random

import networkx as nx
from Backend.Report_Compose.src.ResultsDAG import ResultsDAG
from Backend.Report_Compose.src.PromptManager import PromptManager


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
        self.prompt_manager = PromptManager(yaml_file_path)
        self.results_dag = ResultsDAG()
        self.tasks = {}

    async def process_node(self, node_id: int, dag: nx.DiGraph, mock: bool):
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

            if mock:
                # Simulate processing
                process_time = abs(random.gauss(10, 2))
                await asyncio.sleep(process_time)
                node_prompt = self.prompt_manager.get_prompt_by_id(node_id)
                node_name = node_prompt["section_title"]
                result = f"[MOCK] Completed node {node_id} ({node_name})"
                self.results_dag.store_result(node_id, result)
            else:
                # Real logic...
                await asyncio.sleep(1.0)
                self.results_dag.store_result(node_id, f"Real result for node {node_id}")
        except Exception as e:
            self.results_dag.mark_failed(node_id, str(e))

    async def generate_report(
            self,
            company_name: str,
            custom_topic_focuser: str = "",
            mock: bool = False
    ) -> str:
        """
        Process the prompt DAG concurrently.
        Each node is scheduled as soon as its dependencies are complete.
        """
        dag = self.prompt_manager.prompt_dag

        # Initialize each node in ResultsDAG as "pending"
        for node_id in dag.nodes():
            self.results_dag.init_node(node_id)

        # Schedule tasks for each node in topological order so that parent's tasks exist
        for node_id in nx.topological_sort(dag):
            self.tasks[node_id] = asyncio.create_task(self.process_node(node_id, dag, mock))

        # Await all node tasks concurrently
        await asyncio.gather(*self.tasks.values())

        # Return JSON representation of the entire DAG’s results
        return self.results_dag.to_json()
