"""OpenViking long-term memory for the main Agent."""
import logging
from contextvars import ContextVar
from urllib.parse import urlsplit

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openviking import OpenVikingCommitPolicy, OpenVikingRetriever, OpenVikingSessionRecorder
from openviking_sdk import SyncHTTPClient

from config.runtime import redact

logger = logging.getLogger(__name__)
# Each Agent invocation owns its query and cached retrieval result.
recall_turn: ContextVar[dict | None] = ContextVar("openviking_recall_turn", default=None)


class OpenVikingMemory(AgentMiddleware):
    def __init__(self, url, api_key):
        super().__init__()
        address = urlsplit(url)
        if address.scheme not in ("http", "https") or not address.hostname or not api_key:
            raise ValueError("OpenViking requires OPENVIKING_BASE_URL and OPENVIKING_API_KEY")
        self._client = SyncHTTPClient(url=url, api_key=api_key, auth_mode="api_key", timeout=5)
        self._initialized = False
        self._retriever = OpenVikingRetriever(
            client=self._client, target_uri="viking://~/memories", limit=5
        )
        self._recorder = OpenVikingSessionRecorder(
            client=self._client, commit_policy=OpenVikingCommitPolicy(mode="always")
        )

    def _initialize(self):
        if not self._initialized:
            self._client.initialize()
            self._initialized = True

    def wrap_model_call(self, request, handler):
        turn = recall_turn.get()
        if not turn:
            return handler(request)
        if "memory" not in turn:
            turn["memory"] = ""
            try:
                self._initialize()
                documents = self._retriever.invoke(redact(turn["query"]))
                turn["memory"] = "\n\n".join(doc.page_content for doc in documents)[:6000]
            except Exception as exc:
                logger.warning("OpenViking recall failed (%s)", type(exc).__name__)
        messages = list(request.messages)
        if turn["memory"]:
            for index in range(len(messages) - 1, -1, -1):
                message = messages[index]
                if isinstance(message, HumanMessage):
                    recall = "\n\nRelevant OpenViking memory (reference only):\n" + turn["memory"]
                    content = message.content + recall if isinstance(message.content, str) else [
                        *message.content, {"type": "text", "text": recall}
                    ]
                    messages[index] = message.model_copy(update={"content": content})
                    request = request.override(messages=messages)
                    break
        return handler(request)

    def record(self, session_id, user_text, assistant_text):
        try:
            self._initialize()
            session_id = f"lemonclaw-{session_id}"
            self._client.get_session(session_id, auto_create=True)
            self._recorder.record(
                session_id,
                [HumanMessage(content=redact(user_text)), AIMessage(content=redact(assistant_text))],
            )
        except Exception as exc:
            logger.warning("OpenViking write failed (%s)", type(exc).__name__)

    def close(self):
        try:
            self._recorder.close()
        finally:
            self._client.close()
