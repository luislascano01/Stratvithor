
import threading
import queue
from transformers import pipeline
from typing import Optional

class SummarizationTask:
    def __init__(self, text: str, max_length: int, min_length: int, do_sample: bool = False):
        self.text = text
        self.max_length = max_length
        self.min_length = min_length
        self.do_sample = do_sample
        self.result: Optional[str] = None
        self.event = threading.Event()  # Signals when the task is complete

class SummarizerQueue:
    def __init__(self, summarizer_pipeline: Optional[any] = None, device: int = -1):
        # If no pipeline is provided, instantiate one with the default model.
        if summarizer_pipeline is None:
            summarizer_pipeline = pipeline(
                "summarization",
                model="philschmid/bart-large-cnn-samsum",
                tokenizer="philschmid/bart-large-cnn-samsum",
                device=device  # device=0 for CUDA, -1 for CPU
            )
        self.summarizer = summarizer_pipeline
        self.task_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self.worker, daemon=True)
        self.worker_thread.start()

    def worker(self):
        while True:
            task: SummarizationTask = self.task_queue.get()
            try:
                output = self.summarizer(
                    task.text,
                    max_length=task.max_length,
                    min_length=task.min_length,
                    do_sample=task.do_sample
                )
                task.result = output[0]["summary_text"]
            except Exception as e:
                task.result = None
            finally:
                task.event.set()  # Signal that the task is complete.
                self.task_queue.task_done()

    def summarize(self, text: str, max_length: int, min_length: int, do_sample: bool = False) -> Optional[str]:
        task = SummarizationTask(text, max_length, min_length, do_sample)
        self.task_queue.put(task)
        task.event.wait()  # Wait until the worker finishes the task.
        return task.result

    def __getstate__(self):
        # Exclude non-picklable items (queue and thread) from state.
        state = self.__dict__.copy()
        if "task_queue" in state:
            del state["task_queue"]
        if "worker_thread" in state:
            del state["worker_thread"]
        return state

    def __setstate__(self, state):
        # Restore state and reinitialize non-picklable items.
        self.__dict__.update(state)
        self.task_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self.worker, daemon=True)
        self.worker_thread.start()