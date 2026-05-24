from langchain.agents.middleware import AgentMiddleware

class SerialToolMiddleware(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        request.model_settings = {
            **(request.model_settings or {}),
            "parallel_tool_calls": False,
        }
        return await handler(request)