"""
Server-Sent Events manager for real-time updates

Allows the backend to push notifications to connected clients when events occur,
such as when a DCA transaction is executed.
"""
from typing import Set
import asyncio
from fastapi import Request
from sse_starlette.sse import EventSourceResponse


class SSEManager:
    """Manage Server-Sent Events connections for real-time updates"""
    
    def __init__(self):
        self.active_connections: Set[asyncio.Queue] = set()
    
    async def connect(self, request: Request):
        """
        Handle SSE connection from a client.
        
        Args:
            request: FastAPI request object
            
        Returns:
            EventSourceResponse for SSE streaming
        """
        queue = asyncio.Queue()
        self.active_connections.add(queue)
        
        async def event_generator():
            try:
                while True:
                    # Wait for events
                    if await request.is_disconnected():
                        break
                    
                    try:
                        # Wait for event with timeout
                        event = await asyncio.wait_for(queue.get(), timeout=30.0)
                        yield event
                    except asyncio.TimeoutError:
                        # Send keepalive ping every 30 seconds
                        yield {
                            "event": "ping",
                            "data": "keepalive"
                        }
            finally:
                self.active_connections.remove(queue)
        
        return EventSourceResponse(event_generator())
    
    def broadcast(self, event_type: str, data: dict):
        """
        Broadcast an event to all connected clients.
        
        Args:
            event_type: Type of event (e.g., "transaction_created")
            data: Event data as dictionary
        """
        if not self.active_connections:
            return
        
        event = {
            "event": event_type,
            "data": str(data)
        }
        
        # Add event to all queues
        for queue in self.active_connections:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Skip if queue is full (client might be slow)
                pass


# Global SSE manager instance
sse_manager = SSEManager()
