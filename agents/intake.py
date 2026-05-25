import os
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import RunnableConfig

from db.schemas import IntakeProfile

from .mock_patient import mock_patient_response

load_dotenv()


model = ChatOpenAI(model="gemini-3-flash-preview",
                   base_url="https://ai.hackclub.com/proxy/v1",
                   api_key=os.getenv("HCAI_API_KEY"),
                   temperature=0.7)

with open(os.path.join(__file__, "..", "prompts", "intake_agent_system_prompt.txt")) as f:
    system_prompt = f.read()


@tool
def end_of_intake():
    """Tool to signal the end of the intake process."""
    return "Intake process has been completed."

checkpointer = InMemorySaver()

config: RunnableConfig = {"configurable": {"thread_id": "1"}}

agent = create_agent(model=model,
                     tools=[end_of_intake],
                     system_prompt=system_prompt,
                     checkpointer=checkpointer)

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
async def run_intake_cli(message: str):
    end_intake_called = False
    if message.strip()==".":
        message = await mock_patient_response(agent.get_state(config=config).values["messages"].copy())
        yield f"**Patient:** {message}   \n\n\n\n\n"

    async for chunk in agent.astream(
        {"messages": [{"role": "user", "content": message}]},
        config=config,
        stream_mode=["messages", "updates"],
        version="v2",
    ):
        if chunk["type"] == "messages":
            message_chunk, _metadata = chunk["data"]
            if isinstance(message_chunk.content, str) and message_chunk.content:
                yield message_chunk.content
            continue

        if chunk["type"] != "updates":
            continue

        for _step, data in chunk["data"].items():
            for streamed_message in data.get("messages", []):
                if not getattr(streamed_message, "tool_calls", None):
                    continue
                for call in streamed_message.tool_calls:
                    if call.get("name") == "end_of_intake":
                        end_intake_called = True

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
