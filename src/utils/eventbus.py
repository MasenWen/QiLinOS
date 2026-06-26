class EventBus:
    """事件总线：用于 SSE 推送"""

    def __init__(self):
        from queue import Queue
        self.Queue = Queue
        self.subscribers: dict[int, list] = {}

    def subscribe(self, session_id: int):
        q = self.Queue()
        self.subscribers.setdefault(session_id, []).append(q)

        def unsubscribe():
            arr = self.subscribers.get(session_id, [])
            if q in arr:
                arr.remove(q)

        return q, unsubscribe

    def publish(self, session_id: int, event: dict):
        arr = list(self.subscribers.get(session_id, []))
        for q in arr:
            try:
                if hasattr(q, "put_nowait"):
                    q.put_nowait(event)
                else:
                    q.put(event, block=False)
            except Exception:
                pass


event_bus = EventBus()