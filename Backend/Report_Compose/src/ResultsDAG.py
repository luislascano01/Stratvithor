# ResultsDAG.py

import asyncio
import json
from typing import Any, Dict, Optional, Tuple, AsyncGenerator


class ResultsDAG:
    """
    This class stores the results of each node in a DAG and
    provides a 'watch_updates()' async generator so that any
    subscriber can receive real-time updates whenever a node's
    result is stored or marked as failed.
    """

    def __init__(self) -> None:
        # Maps node_id -> {"status": "pending|complete|failed", "result": Any}
        self.results: Dict[int, Dict[str, Any]] = {}
        # An async queue of updates (node_id, node_data)
        self._updates_queue: asyncio.Queue[Tuple[int, Dict[str, Any]]] = asyncio.Queue()

    def init_node(self, node_id: int) -> None:
        """
        Mark a node as 'pending' with no result. Typically called
        before any processing starts for that node.
        """
        self.results[node_id] = {"status": "pending", "result": None}

    def  store_result(self, node_id: int, result: Any) -> None:
        """
        Mark a node as 'complete' with the given result,
        then push an update event to our queue.
        """
        self.results[node_id] = {"status": "complete", "result": result}
        self._updates_queue.put_nowait((node_id, self.results[node_id]))

    def mark_failed(self, node_id: int, error_msg: str) -> None:
        """
        Mark a node as 'failed' and store the error message,
        then push an update event to our queue.
        """
        self.results[node_id] = {"status": "failed", "result": error_msg}
        self._updates_queue.put_nowait((node_id, self.results[node_id]))

    def get_result(self, node_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve the result dict (status, result) for a specific node.
        """
        return self.results.get(node_id)

    def to_json(self) -> str:
        """
        Return a JSON representation of all stored node results.
        """
        return json.dumps(self.results, indent=2)

    def mark_processing(self, node_id: int, msg: str = "") -> None:
        """
        Mark a node as 'processing' with an optional message,
        then push an update event to our queue.
        """
        self.results[node_id] = {"status": "processing", "result": msg}
        self._updates_queue.put_nowait((node_id, self.results[node_id]))

    async def watch_updates(self) -> AsyncGenerator[Tuple[int, Dict[str, Any]], None]:
        """
        An async generator that yields (node_id, node_data) whenever
        a node is updated. Ideal for streaming via WebSocket.
        """
        while True:
            node_id, node_data = await self._updates_queue.get()
            yield node_id, node_data