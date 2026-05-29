import os
from typing import AsyncGenerator
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import RunnableConfig

from agents.shared import create_agent_by_type
from db.schemas import IntakeProfile
from agents.inference import run_inference

from .mock_patient import mock_patient_response

load_dotenv()


model = ChatOpenAI(model=os.getenv("INTAKE_AGENT_MODEL") or "google/gemini-3-flash-preview",
                   base_url=os.getenv("AI_API_BASE_URL") or "https://ai.hackclub.com/proxy/v1",
                   api_key=os.getenv("AI_API_KEY"),
                   temperature=0.7)

with open(os.path.join(__file__, "..", "prompts", "intake_agent_system_prompt.txt")) as f:
    system_prompt = f.read()


@tool("end_of_intake", return_direct=True)
def end_of_intake():
    """Tool to signal the end of the intake process."""
    return "Intake process has been completed."

@tool("infer_condition")
async def infer_condition(summary: str) -> str:
    """Tool to infer potential conditions based on patient's chief complaint and HPI.
    The input should be a markdown-formatted summary of the patient's chief complaint and HPI details."""
    
    return await run_inference(summary)

checkpointer = InMemorySaver()

config: RunnableConfig = {"configurable": {"thread_id": "1"}}

agent = create_agent_by_type("intake", tools=[end_of_intake, infer_condition], system_prompt=system_prompt, checkpointer=checkpointer)

messages = [
    # {"role": "system", "content": system_prompt},
    {"role": "assistant", "content": "What brings you in today?"}
]

agent.update_state(config=config, values={"messages": messages})

def run_intake() -> tuple[IntakeProfile, list[dict[str,str]]]:
    # Deprecated
    print("Assistant: What brings you in today? (Type 'quit' to exit)")
    
    while True:
        user_input = mock_patient_response(agent.get_state(config=config).values["messages"].copy())
        print(f"\nPatient: {user_input}\n")
        # if user_input.lower() in ["quit", "exit"]:
        #     break

        try:
            response = agent.invoke(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config,
            )
                    
            end_intake_called = False
            if "messages" in response:
                for msg in response["messages"]:
                    if getattr(msg, "tool_calls", None):
                        for call in msg.tool_calls:
                            if call.get("name") == "end_of_intake":
                                end_intake_called = True
                                break
            
            if end_intake_called:
                print("\nAssistant: Thank you for your time. The intake is now complete.")
                break
            
            response["messages"][-1].pretty_print() 

        except Exception as e:
            print(f"\nError: {e}\n")

    print("\n--- INTAKE COMPLETE ---")
    print("Compiling dense medical summary and structured patient data...\n")

    # Use with_structured_output to enforce the IntakeProfile format ONLY at the end
    model.temperature = 0.3  # Lower temperature for more deterministic output
    structured_model = model.with_structured_output(IntakeProfile)

    try:
        # We pass the entire conversation history to generate the final structured output
        conversation_state = agent.get_state(config=config)
        final_patient_data = structured_model.invoke(conversation_state.values["messages"])
        print("=== FINAL PATIENT INFO (JSON) ===")
        print(final_patient_data.model_dump_json(indent=2))
        
    except Exception as e:
        print(f"\nFailed to generate final report: {e}")
    
    return final_patient_data, agent.get_state(config=config).values["messages"]


#TODO: Have the model NOT produce an output normally in conversation. all we need will be produced at structured call
def _iter_stream_text(content: str | list[dict] | None):
    if isinstance(content, str):
        if content:
            yield content
        return

    if not isinstance(content, list):
        return

    for block in content:
        if not isinstance(block, dict):
            continue

        if block.get("type") == "text" and block.get("text"):
            yield block["text"]

#TODO: Take demographics at the start before starting intake, no chat approach, then pass demographics to intake agent.
async def run_intake_cli(message: str) -> AsyncGenerator[str | dict | tuple[IntakeProfile, list[dict[str, str]]], None]:
    end_intake_called = False
    infer_condition_active = False
    if message.strip() == ".":
        message = await mock_patient_response(agent.get_state(config=config).values["messages"].copy())
        yield f"**Patient:** {message}   \n\n\n\n\n"

    async for event in agent.astream_events(
        {"messages": [{"role": "user", "content": message}]},
        config=config,
        version="v2",
    ):
        if event["event"] == "on_tool_start":
            if event.get("name") == "end_of_intake":
                end_intake_called = True

            elif event.get("name") == "infer_condition":
                infer_condition_active = True
                # tool_input = event["data"]["input"]["summary"]
                yield {"type": "tool_start", "name": "infer_condition"}
            continue

        elif event["event"] == "on_tool_end":
            if event.get("name") == "infer_condition":
                infer_condition_active = False
                yield {"type": "tool_end", "name": "infer_condition"}
            continue

        if event["event"] == "on_chat_model_stream":
            if infer_condition_active:
                continue

            chunk: AIMessageChunk = event["data"]["chunk"]
            for text in _iter_stream_text(chunk.content):
                yield text

    if end_intake_called:
        yield "END"
        model.temperature = 0.3  # Lower temperature for more deterministic output
        structured_model = model.with_structured_output(IntakeProfile)

        try:
            conversation_state = agent.get_state(config=config)
            final_patient_data = await structured_model.ainvoke(conversation_state.values["messages"])

            yield f"I have compiled the final patient data."
            yield final_patient_data, conversation_state.values["messages"]
        except Exception as e:
            print(f"\nFailed to generate final report: {e}")

if __name__ == "__main__":
    async def main():
        async for chunk in run_intake_cli("I have abdominal pain"):
            print(chunk)
            
    import asyncio
    asyncio.run(main())
