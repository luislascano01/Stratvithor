import yaml
import os
from asciitree import LeftAligned
from collections import defaultdict
import networkx as nx  # Using networkx to handle and validate DAG structures

class PromptManager:
    def __init__(self, yaml_file_path):
        self.prompts = {}  # Dictionary of dictionaries
        self.prompt_id_map = {}  # Dictionary mapping ID -> prompt object
        self.prompt_dag = nx.DiGraph()  # Directed Acyclic Graph (DAG) of prompt dependencies
        self.load_prompts(yaml_file_path)

    def load_prompts(self, yaml_file_path):
        """Load prompts from a YAML file and store them in a nested dictionary."""
        with open(yaml_file_path, 'r', encoding='utf-8') as file:
            data = yaml.safe_load(file)

        prompts_data = data.get("prompts", {})  # Ensure it doesn't crash if 'prompts' key is missing
        dag_data = data.get("prompt_dag", [])  # Load DAG structure from YAML

        for section_title, prompt_data in prompts_data.items():
            if isinstance(prompt_data, dict) and "text" in prompt_data:  # Ensure it's a dictionary and contains text
                prompt_id = prompt_data.get("id")  # Get prompt ID

                if prompt_id is None:
                    raise ValueError(f"Prompt '{section_title}' is missing an ID.")

                prompt_obj = {
                    "section_title": prompt_data.get("section_name", section_title),  # Use section_name if available
                    "text": prompt_data["text"],
                    "id": prompt_id,
                    "system": prompt_data.get("system", False),
                    "additional_data": {}
                }

                # Store prompts in both name-based and ID-based dictionaries
                self.prompts[section_title] = prompt_obj
                self.prompt_id_map[prompt_id] = prompt_obj

        # Load DAG structure and validate it
        self.load_dag(dag_data)

    def load_dag(self, dag_data):
        """Load and validate the Directed Acyclic Graph (DAG) of prompts."""
        for edge in dag_data:
            nodes = list(map(int, edge.split("->")))  # Convert node IDs from string to int
            # Iterate over the chain of nodes and create edges between consecutive nodes
            for i in range(len(nodes) - 1):
                self.prompt_dag.add_edge(nodes[i], nodes[i + 1])

        # Validate that the resulting graph is a DAG
        if not nx.is_directed_acyclic_graph(self.prompt_dag):
            raise ValueError("Invalid DAG detected! The prompt dependencies contain cycles.")

    def add_metadata(self, prompt, key, value):
        """Add extra metadata under a given prompt."""
        if prompt in self.prompts:
            self.prompts[prompt]["additional_data"][key] = value
        else:
            print(f"Prompt '{prompt}' not found.")

    def get_prompt_data(self, prompt):
        """Retrieve stored data for a given prompt by section name."""
        return self.prompts.get(prompt, None)

    def get_prompt_by_id(self, prompt_id):
        """Retrieve stored data for a given prompt by ID."""
        return self.prompt_id_map.get(prompt_id, None)

    def get_prompt_dependencies(self, prompt_id):
        """Return a list of direct dependencies (parent prompts) for a given prompt ID."""
        if prompt_id not in self.prompt_dag:
            return None
        return list(self.prompt_dag.predecessors(prompt_id))

    def get_prompt_dependents(self, prompt_id):
        """Return a list of direct dependents (child prompts) for a given prompt ID."""
        if prompt_id not in self.prompt_dag:
            return None
        return list(self.prompt_dag.successors(prompt_id))

    def get_dag_ascii(self):
        """Generate an ASCII representation of the DAG with correct spacing and centering."""
        import networkx as nx
        from collections import defaultdict

        # Step 1: Identify root nodes (nodes with no predecessors)
        roots = [node for node in self.prompt_dag.nodes() if self.prompt_dag.in_degree(node) == 0]
        if not roots:
            return "Error: No root nodes found in the DAG."

        # Step 2: Compute node depths (levels) using topological sorting
        node_depths = {}  # {node: depth}
        depth_nodes = defaultdict(list)  # {depth: [nodes]}
        node_widths = {}  # {node: width required for its subtree}

        sorted_nodes = list(nx.topological_sort(self.prompt_dag))
        for node in sorted_nodes:
            if self.prompt_dag.in_degree(node) == 0:
                node_depths[node] = 0
            else:
                node_depths[node] = max(node_depths[parent] + 1 for parent in self.prompt_dag.predecessors(node))
            depth_nodes[node_depths[node]].append(node)

        # Step 3: Compute subtree widths (bottom-up)
        def compute_widths(node):
            """Recursively compute the width needed for a node's subtree."""
            children = list(self.prompt_dag.successors(node))
            if not children:
                node_widths[node] = 3  # Minimum width for a leaf
                return 3
            width = sum(compute_widths(child) for child in children) + (len(children) - 1)
            node_widths[node] = max(width, len(str(node)) + 2)  # Ensure enough space for the label
            return node_widths[node]

        for node in reversed(sorted_nodes):
            compute_widths(node)

        # Step 4: Assign horizontal positions (top-down)
        node_positions = {}  # {node: x_position}

        def assign_positions(node, x_offset):
            """Recursively assign x positions to nodes for proper centering."""
            children = list(self.prompt_dag.successors(node))
            if not children:
                node_positions[node] = x_offset
                return x_offset + node_widths[node]
            child_x_positions = []
            for child in children:
                x_offset = assign_positions(child, x_offset)
                child_x_positions.append(node_positions[child])
            # Center this node over its children
            node_positions[node] = sum(child_x_positions) // len(child_x_positions)
            return x_offset

        assign_positions(roots[0], 0)

        # Step 5: Build the ASCII representation
        ascii_output = []
        max_x = max(node_positions.values()) + 4  # Define the canvas width

        def format_line(nodes):
            """Format a single line with nodes placed at their x positions."""
            line = [" "] * (max_x + 10)
            for node in nodes:
                pos = node_positions[node]
                s = str(node)
                # Center the label around its x position
                start = pos - len(s) // 2
                for i, ch in enumerate(s):
                    if 0 <= start + i < len(line):
                        line[start + i] = ch
            return "".join(line)

        def format_edges(parents, children):
            """Format the edge lines connecting parent nodes to child nodes."""
            edge_line = [" "] * (max_x + 10)
            conn_line = [" "] * (max_x + 10)
            for parent in parents:
                for child in children:
                    if child in self.prompt_dag.successors(parent):
                        parent_x = node_positions[parent]
                        child_x = node_positions[child]
                        if child_x == parent_x:
                            edge_line[parent_x] = "|"
                            conn_line[parent_x] = "|"
                        elif child_x < parent_x:
                            edge_line[parent_x] = "|"
                            conn_line[child_x] = "/"
                        else:
                            edge_line[parent_x] = "|"
                            conn_line[child_x] = "\\"
            return "".join(edge_line) + "\n" + "".join(conn_line)

        sorted_depths = sorted(depth_nodes.keys())
        for i, depth in enumerate(sorted_depths):
            ascii_output.append(format_line(depth_nodes[depth]))
            if i < len(sorted_depths) - 1:
                parents = depth_nodes[depth]
                children = depth_nodes[sorted_depths[i + 1]]
                ascii_output.append(format_edges(parents, children))

        return "\n".join(ascii_output)

    def get_dag_latex(self):
        """
        Produce a LaTeX document with TikZ that lays out the DAG in distinct
        horizontal layers (rows) based on each node's depth. Nodes at the
        same depth appear side by side, ensuring we don't get a single column.

        Steps:
          1) Topological sort the graph.
          2) Compute depth[node] = max depth of parent + 1.
          3) Group nodes by depth.
          4) Place them horizontally left->right in ascending order.
          5) Draw directed edges.
        """
        import networkx as nx
        from collections import defaultdict

        # 1) Topological Sort to get a valid order
        sorted_nodes = list(nx.topological_sort(self.prompt_dag))

        # 2) Compute depth for each node
        node_depth = {}
        for node in sorted_nodes:
            preds = list(self.prompt_dag.predecessors(node))
            if not preds:
                node_depth[node] = 0
            else:
                node_depth[node] = max(node_depth[p] for p in preds) + 1

        # Group nodes by depth
        depth_map = defaultdict(list)
        for node in sorted_nodes:
            depth_map[node_depth[node]].append(node)

        # Sort each depth layer so nodes appear left-to-right in ascending order
        for d in depth_map:
            depth_map[d].sort()

        # 3) Build the LaTeX document
        latex_lines = [
            r"\documentclass[tikz]{standalone}",
            r"\usepackage{tikz}",
            r"\usetikzlibrary{arrows, positioning}",
            r"\begin{document}",
            r"\begin{tikzpicture}[>=stealth, every node/.style={draw, circle, minimum size=2cm}]"
        ]

        # We'll store each node's TikZ name for referencing in edges
        node_positions = {}  # {node: (x_coord, y_coord)}
        tikz_node_names = {}  # {node: "N{node}"}

        # 4) Place nodes in layers
        layer_y_distance = 3.0  # vertical distance between layers
        node_x_distance = 3.0  # horizontal distance among siblings

        sorted_depths = sorted(depth_map.keys())
        for depth in sorted_depths:
            nodes_at_depth = depth_map[depth]
            # We'll center them around x=0. So the leftmost node is at x = -((count-1)/2)*node_x_distance
            count = len(nodes_at_depth)
            start_x = -((count - 1) / 2.0) * node_x_distance
            y_coord = -(depth * layer_y_distance)

            for i, node in enumerate(nodes_at_depth):
                x_coord = start_x + i * node_x_distance
                tikz_node_name = f"N{node}"
                tikz_node_names[node] = tikz_node_name
                node_positions[node] = (x_coord, y_coord)

                latex_lines.append(
                    f"\\node ({tikz_node_name}) at ({x_coord:.2f}, {y_coord:.2f}) {{{node}}};"
                )

        # 5) Draw edges
        for parent, child in self.prompt_dag.edges():
            latex_lines.append(
                f"\\draw[->] ({tikz_node_names[parent]}) -- ({tikz_node_names[child]});"
            )

        latex_lines.append(r"\end{tikzpicture}")
        latex_lines.append(r"\end{document}")

        return "\n".join(latex_lines)


    def display_prompts(self):
        """Print all stored prompts in a readable format."""
        import textwrap
        prompt_text_wrap_indent = "    "
        for prompt, details in self.prompts.items():
            print(f"Prompt: {prompt}")
            print(f"  Section Title: {details['section_title']}")
            wrapped_text = textwrap.fill(details['text'], width=50,
                                         subsequent_indent=prompt_text_wrap_indent)  # Wrap text to 50 chars with indent
            print(f"  Prompt Text:\n{prompt_text_wrap_indent}{wrapped_text}")
            print(f"  Additional Data: {details['additional_data']}")
            print(f"  ID: {details['id']}")
            print(f"  System: {details['system']}")
            print(f"  Dependencies: {self.get_prompt_dependencies(details['id'])}")
            print(f"  Dependents: {self.get_prompt_dependents(details['id'])}")
            print("-" * 40)

if __name__ == "__main__":
    manager = PromptManager("./Prompts/prompts.yaml")
    manager.display_prompts()

    # Test DAG functionality
    test_id = 2
    print(f"\nDependencies of prompt ID {test_id}: {manager.get_prompt_dependencies(test_id)}")
    print(f"Dependents of prompt ID {test_id}: {manager.get_prompt_dependents(test_id)}")

    print("Ascii tree:\n\n")
    print(manager.get_dag_ascii() + "\n")

    print("Latex code:\n\n")
    print(manager.get_dag_latex())