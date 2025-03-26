import unittest
import os
import json
import tempfile
import networkx as nx
from unittest.mock import MagicMock, patch
from docx import Document

# If your real Integrator code is located elsewhere, adjust the import below.
# from Backend.Report_Compose.src.Integrator import Integrator
class Integrator:
    def __init__(self, yaml_file_path=None):
        self.results_dag = None
        self.prompt_manager = None
        self.yaml_file_path = yaml_file_path
        self.focus_message = None

    def generate_docx_report(self, llm_format: str = "Markdown") -> str:
        """Placeholder referencing the real implementation."""
        raise NotImplementedError("Replace this stub with the real Integrator code.")


@patch.object(Integrator, 'generate_docx_report',
             autospec=True,
             side_effect=None)  # We'll remove this patch once we use the real method
def dummy_test_generate_docx_report(*args, **kwargs):
    pass


class TestReportGeneration(unittest.TestCase):
    def setUp(self):
        """
        Create a minimal Integrator object with a mock DAG and results.
        """
        # 1) Create a small directed acyclic graph in NetworkX.
        #    For example, 1 -> 2
        dag = nx.DiGraph()
        dag.add_edge(1, 2)

        # 2) Stub out some final DAG results in JSON form.
        #    In real usage, these come from `self.results_dag.to_json()`.
        self.mock_results = {
            "1": {
                "result": {
                    "section_title": "Introduction",
                    "llm": "Here is some introduction text."
                }
            },
            "2": {
                "result": {
                    "section_title": "Conclusion",
                    "llm": "Final remarks go here."
                }
            }
        }

        # 3) Build an absolute path to the YAML file
        #    (assuming it's located in a Prompts/ subfolder adjacent to this test file).
        current_dir = os.path.dirname(__file__)
        yaml_file_path = os.path.join(current_dir, "Prompts", "Luis_Prompts.yaml")

        # 4) Instantiate the real Integrator. (Update with your actual import as needed.)
        # from Backend.Report_Compose.src.Integrator import Integrator
        self.integrator = Integrator(yaml_file_path)

        # 5) Attach a mock results DAG and prompt manager to the integrator
        class MockResultsDAG:
            def to_json(_):
                return json.dumps(self.mock_results)

        self.integrator.results_dag = MockResultsDAG()

        class MockPromptManager:
            pass

        mock_pm = MockPromptManager()
        mock_pm.prompt_dag = dag
        self.integrator.prompt_manager = mock_pm

        # 6) Provide a real or mock YAML file path and focus message so the integrator doesn't break.
        self.integrator.yaml_file_path = os.path.join(current_dir, "Prompts", "DemoPrompts.yaml")
        self.integrator.focus_message = "A test focus message."

    def test_generate_docx_report_happy_path(self):
        """
        Test that generate_docx_report creates a docx file
        and that the docx contains the expected headings and text.
        """
        # 1) Call the real method (now that we have a real integrator).
        docx_path = self.integrator.generate_docx_report(llm_format="Markdown")

        # 2) Check that the function returned a path and that the file exists.
        self.assertTrue(os.path.exists(docx_path),
                        msg="The DOCX report file should be created on disk.")

        # 3) Read the docx with python-docx to verify its contents.
        doc = Document(docx_path)
        paragraphs = [p.text for p in doc.paragraphs]

        # Basic checks: heading and main text
        self.assertIn("Aggregated Report", paragraphs[0],
                      "Document should begin with 'Aggregated Report' heading.")

        # Additional checks: ensures our example text is inserted
        joined_paragraphs = "\n".join(paragraphs)
        self.assertIn("Introduction", joined_paragraphs,
                      "Should contain the section title for node #1.")
        self.assertIn("Conclusion", joined_paragraphs,
                      "Should contain the section title for node #2.")

        # 4) Cleanup: remove the temporary docx
        os.remove(docx_path)

    def test_generate_docx_report_unsupported_format(self):
        """
        Test that an unsupported llm_format raises the expected Exception.
        """
        with self.assertRaises(Exception) as context:
            # Something other than "Markdown" or your recognized formats
            self.integrator.generate_docx_report(llm_format="LaTeX")

        self.assertIn("Unsupported llm_format", str(context.exception),
                      "The method should raise an exception for unsupported formats.")


if __name__ == "__main__":
    unittest.main()