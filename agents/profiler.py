import uuid
from pydantic import BaseModel

from langgraph.config import RunnableConfig

from agents.shared import create_agent_by_type
import local_worker.store as store
from db.schemas import ChatSessionData

async def build_chat_session_data_to_string(chat_session_data: ChatSessionData):
    """
    Convert ChatSessionData to a string representation for logging or processing.
    """
    intake_session = chat_session_data.intake_session.model_dump() if chat_session_data.intake_session else {}
    intake_session_str = (
        "<intake-session>\n"
        f"Chief Complaint: {intake_session.get('chief_complaint')}\n"
        f"Symptoms: {intake_session.get('symptoms', [])}\n"
        f"Medical Summary: {intake_session.get('medical_summary')}\n"
        "</intake-session>\n"
    ) if intake_session else ""
    
    research_sessions = chat_session_data.research_sessions or []
    research_sessions_str = "\n".join(
        f"<research-session>\n"
        f"Research Report: {session.research_report}\n"
        f"</research-session>"
        for session in research_sessions
    )
    
    diagnosis_session = chat_session_data.diagnosis_session
    diagnosis_session_str = (
        f"<diagnosis-session>\n"
        f"Report: {diagnosis_session.report}\n"
        f"</diagnosis-session>\n"
        if diagnosis_session
        else ""
    )
    
    doctor_session_messages = []
    if chat_session_data.doctor_session_id:
        checkpoint = await store.get_checkpointer().aget_tuple(
            {"configurable": {"thread_id": str(chat_session_data.doctor_session_id)}}
        )
        if checkpoint:
            doctor_session_messages = checkpoint.checkpoint["channel_values"].get("messages", [])

    def message_value(message, key):
        if isinstance(message, dict):
            return message.get(key)
        if key == "role":
            return getattr(message, "type", None)
        return getattr(message, key, None)

    doctor_session_messages = [
        message for message in doctor_session_messages
        if message_value(message, "role") in ["user", "human", "assistant", "ai"]
    ]
    
    doctor_session_str = "\n".join(
        f"<doctor-session-message>\n"
        f"Role: {message_value(msg, 'role')}\n"
        f"Content: {message_value(msg, 'content')}\n"
        f"</doctor-session-message>"
        for msg in doctor_session_messages
    )
    
    return (
        f"Chat Session Data:\n\n"
        f"{intake_session_str}\n"
        f"{research_sessions_str}\n"
        f"{diagnosis_session_str}\n"
        f"{doctor_session_str}\n"
    )

class UserProfileUpdate(BaseModel):
    user_profile: str

async def update_user_profile_with_chat_session(chat_session_data: ChatSessionData, user_profile_str: str):
    
    agent = create_agent_by_type("profiler", tools=[], response_format=UserProfileUpdate)
    config: RunnableConfig = {"configurable": {"thread_id": str(uuid.uuid4())}}
    
    response = await agent.ainvoke(
        {"messages": [{"role": "user", 
                       "content": f"Update user profile with new chat session data.\n \
Chat Session Data: {await build_chat_session_data_to_string(chat_session_data)}\n\n \
User Profile:\n {user_profile_str}"}]},
        config=config,
    )

    structured_response = response["structured_response"]
    if isinstance(structured_response, UserProfileUpdate):
        return structured_response.user_profile
    return structured_response.get("user_profile")
