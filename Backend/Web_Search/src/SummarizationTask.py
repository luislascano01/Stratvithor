
import threading
import time
from typing import Optional
from dataclasses import dataclass, field
import heapq

@dataclass(order=True)
class SummarizationTask:
    """
    A data class representing a summarization request with priority ordering.
    Lower 'priority' means processed first in a PriorityQueue.
    """
    priority: int
    text: str = field(compare=False)
    max_length: int = field(default=200, compare=False)
    min_length: int = field(default=30, compare=False)
    do_sample: bool = field(default=False, compare=False)
    deadline: Optional[float] = field(default=None, compare=False)
    result: Optional[str] = field(default=None, compare=False)
    event: threading.Event = field(default_factory=threading.Event, compare=False)

    def expired(self) -> bool:
        """Return True if the task's deadline has passed."""
        return (self.deadline is not None) and (time.time() > self.deadline)
import threading
import heapq
import time
from queue import Empty
from transformers import pipeline
import torch

class PrioritySummarizerQueue:
    """
    A single-GPU summarizer queue that processes tasks in priority order (lowest priority number first).
    Once the queue is empty, we optionally offload the model.
    """

    def __init__(self, summarizer_pipeline=None, device: int = 0, unload_when_idle: bool = True):
        """
        :param summarizer_pipeline: Optionally pass an existing HF pipeline.
        :param device: 0 for GPU, -1 for CPU, etc.
        :param unload_when_idle: If True, automatically unloads model when queue is empty.
        """
        if summarizer_pipeline is None:
            summarizer_pipeline = pipeline(
                "summarization",
                model="philschmid/bart-large-cnn-samsum",
                tokenizer="philschmid/bart-large-cnn-samsum",
                device=device  # 0 for GPU, -1 for CPU
            )
        self.summarizer = summarizer_pipeline
        self.unload_when_idle = unload_when_idle

        # We'll store tasks in a min-heap
        self._heap = []
        self._heap_lock = threading.Lock()

        # A condition variable to notify the worker when new tasks arrive
        self._cv = threading.Condition(self._heap_lock)

        # Used to signal the worker to exit
        self._shutdown_flag = False

        # Start worker thread
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def summarize_async(self, text: str, priority: int = 10, max_length: int = 200,
                        min_length: int = 30, do_sample: bool = False,
                        deadline: float = None):
        """
        Enqueue a new SummarizationTask. Returns the task object immediately.
        The caller can wait on task.event or check task.result asynchronously.
        :param priority: Lower = higher priority.
        :param deadline: A timestamp (time.time() + N). If time passes that, we skip it.
        """
        task = SummarizationTask(priority, text, max_length, min_length, do_sample, deadline)
        with self._cv:
            heapq.heappush(self._heap, task)
            self._cv.notify()  # Wake the worker
        return task

    def summarize_blocking(self, text: str, priority: int = 10, max_length: int = 200,
                           min_length: int = 30, do_sample: bool = False,
                           deadline: float = None) -> str:
        """
        Synchronous summarization call. Pushes a task, waits for it to finish, returns the result.
        """
        task = self.summarize_async(text, priority, max_length, min_length, do_sample, deadline)
        task.event.wait()  # Wait until the worker finishes
        return task.result or ""

    def _worker_loop(self):
        """
        Continuously pop tasks from the priority heap, summarize them, and set result.
        If queue is empty and unload_when_idle is True, unload the model from GPU until new tasks come in.
        """
        while True:
            with self._cv:
                while not self._heap and not self._shutdown_flag:
                    # Possibly unload the model if configured
                    if self.unload_when_idle and self.summarizer is not None:
                        self._unload_model()
                    self._cv.wait()

                if self._shutdown_flag:
                    # Flush leftover tasks
                    while self._heap:
                        task = heapq.heappop(self._heap)
                        task.result = None
                        task.event.set()
                    return

                task = heapq.heappop(self._heap)

            # We have a task. Possibly reload model if it was unloaded
            if self.summarizer is None:
                self._reload_model()

            # Check if expired
            if task.expired():
                task.result = None
                task.event.set()
                continue

            # Summarize
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
                task.event.set()

    def flush_all(self):
        """
        Clear all pending tasks from the queue.
        Already-running task in worker won't be interrupted, but no new tasks will be processed.
        """
        with self._cv:
            while self._heap:
                t = heapq.heappop(self._heap)
                t.result = None
                t.event.set()

    def shutdown(self):
        """
        Signal the worker to exit, flush tasks, and join the thread.
        """
        with self._cv:
            self._shutdown_flag = True
            self._cv.notify_all()
        self.worker_thread.join()
        # Optionally unload the model here too
        self._unload_model()

    def _unload_model(self):
        """
        Frees GPU memory by deleting the pipeline and calling torch.cuda.empty_cache().
        """
        if self.summarizer is not None:
            del self.summarizer
            self.summarizer = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _reload_model(self):
        """
        Reloads the summarization model onto the GPU if it was unloaded.
        """
        if self.summarizer is None:
            self.summarizer = pipeline(
                "summarization",
                model="philschmid/bart-large-cnn-samsum",
                tokenizer="philschmid/bart-large-cnn-samsum",
                device=0
            )

    # Optional: allow immediate usage, skipping the background thread if you want
    # a direct call that doesn't rely on the queue or re-raises exceptions, etc.

    def __del__(self):
        """Attempt a graceful shutdown if not already done."""
        try:
            self.shutdown()
        except:
            pass