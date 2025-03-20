import time
import torch
import multiprocessing
from dataclasses import dataclass, field
from transformers import pipeline
import uuid

# -----------------------------------------------------------------------------
# Data classes for requests and responses
# -----------------------------------------------------------------------------
@dataclass(order=True)
class SummarizationRequest:
    priority: int
    request_id: str = field(compare=False)
    text: str = field(compare=False)
    max_length: int = field(default=300, compare=False)
    min_length: int = field(default=30, compare=False)
    do_sample: bool = field(default=False, compare=False)
    deadline: float = field(default=None, compare=False)

@dataclass
class SummarizationResponse:
    request_id: str
    summary_text: str = ""
    error: str = ""

# -----------------------------------------------------------------------------
# The single GPU summarizer service class
# -----------------------------------------------------------------------------
class SingleGPUSummarizerService:
    """
    A single-GPU summarizer service. Only one process loads the heavy GPU pipeline.
    Client processes send SummarizationRequest objects via a queue and receive
    SummarizationResponse objects from a response queue.

    NOTE: This minimal fix uses a regular multiprocessing.Queue rather than
          a PriorityQueue. Requests are handled in FIFO order (not by priority).
    """
    def __init__(self, device: int = 0):
        """
        Initializes the service by creating the IPC queues and launching the service process.
        :param device: 0 for GPU (if available), -1 for CPU.
        """
        self.device = device
        self.request_queue = multiprocessing.Queue()
        self.response_queue = multiprocessing.Queue()

        self.process = multiprocessing.Process(
            target=self._service_loop,
            args=(self.request_queue, self.response_queue, self.device),
            daemon=True
        )
        self.process.start()

    def _insert_linebreaks(self, text: str, words_per_line: int = 20) -> str:
        """
        Inserts a double newline every `words_per_line` words to format the text into paragraphs.
        """
        words = text.split()
        lines = []
        for i in range(0, len(words), words_per_line):
            lines.append(" ".join(words[i:i + words_per_line]))
        return "\n\n".join(lines)

    def _service_loop(self, request_queue, response_queue, device):
        """
        The main loop of the GPU summarizer service.
        It loads the summarization pipeline on the given device and processes incoming requests.
        """
        print(f"[GPU Service] Loading summarizer pipeline on device {device} ...")
        summarizer = pipeline(
            "summarization",
            model="philschmid/bart-large-cnn-samsum",
            tokenizer="philschmid/bart-large-cnn-samsum",
            device=device
        )
        print("[GPU Service] Pipeline loaded.")

        tokenizer = summarizer.tokenizer
        max_input_length = tokenizer.model_max_length  # e.g., 1024 for many models

        while True:
            req = request_queue.get()
            if req is None:
                break

            if req.deadline is not None and time.time() > req.deadline:
                resp = SummarizationResponse(
                    request_id=req.request_id,
                    error="Deadline expired"
                )
                response_queue.put(resp)
                continue

            if torch.cuda.is_available() and device >= 0:
                total_mem = torch.cuda.get_device_properties(device).total_memory
                while torch.cuda.memory_allocated(device) > 0.95 * total_mem:
                    time.sleep(0.5)

            try:
                # Pre-truncate input if needed.
                encoded_input = tokenizer.encode(req.text, truncation=True)
                if len(encoded_input) > max_input_length:
                    req_text = tokenizer.decode(encoded_input[:max_input_length])
                else:
                    req_text = req.text

                output = summarizer(
                    req_text,
                    max_length=req.max_length,
                    min_length=req.min_length,
                    do_sample=req.do_sample,
                    truncation=True
                )
                summary_text = output[0]["summary_text"]
                # Format the summary by inserting line breaks every 20 words.
                formatted_summary = self._insert_linebreaks(summary_text, words_per_line=20)
                resp = SummarizationResponse(
                    request_id=req.request_id,
                    summary_text=formatted_summary
                )
            except Exception as e:
                resp = SummarizationResponse(
                    request_id=req.request_id,
                    error=f"{type(e).__name__}: {str(e)}"
                )

            response_queue.put(resp)

        del summarizer
        print("[GPU Service] Service loop exiting.")

    def submit_request(self, text: str, priority: int = 10,
                       max_length: int = 300, min_length: int = 30,
                       do_sample: bool = False, deadline: float = None) -> str:
        """
        Submits a summarization request to the service.
        Returns the generated unique request_id.
        """
        request_id = str(uuid.uuid4())
        req = SummarizationRequest(
            priority=priority,
            request_id=request_id,
            text=text,
            max_length=max_length,
            min_length=min_length,
            do_sample=do_sample,
            deadline=deadline
        )
        self.request_queue.put(req)
        return request_id

    def get_response(self, request_id: str, timeout: float = None) -> SummarizationResponse:
        """
        Blocks until the response with the given request_id is found.
        (For simplicity, this example uses a polling method.)
        """
        start = time.time()
        while True:
            try:
                resp = self.response_queue.get(timeout=timeout)
                if resp.request_id == request_id:
                    return resp
            except Exception:
                break
            if timeout is not None and (time.time() - start) > timeout:
                break

        return SummarizationResponse(
            request_id=request_id,
            error="Response not found within timeout"
        )

    def shutdown(self):
        """
        Shuts down the service by sending a sentinel value to the request queue and joining the process.
        """
        self.request_queue.put(None)
        self.process.join()


# -----------------------------------------------------------------------------
# Example usage (only runs if executed directly)
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    service = SingleGPUSummarizerService(device=0)

    sample_text = (
        "Tesla is a technology and automotive company that designs, develops, "
        "and manufactures electric vehicles, energy storage systems, and solar products. "
        "It has revolutionized the automotive industry with its cutting-edge technology. "
        "Recent reports indicate that Tesla generated impressive revenue figures, with "
        "significant EBITDA margins and a carefully managed debt balance sheet."
    )

    req_id = service.submit_request(sample_text, priority=10, max_length=150, min_length=30)
    print(f"[Main] Submitted summarization request with ID: {req_id}")

    response = service.get_response(req_id, timeout=30)
    if response.error:
        print(f"[Main] Error: {response.error}")
    else:
        print(f"[Main] Summary:\n{response.summary_text}")

    service.shutdown()
    print("[Main] GPU summarizer service has been shut down.")
