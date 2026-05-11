import os
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import RunnableConfig

from pydantic import BaseModel, Field
from typing import Optional

load_dotenv()

DATABASE = {}


model = ChatOpenAI(model="gemini-3-flash-preview",
                   base_url="https://ai.hackclub.com/proxy/v1",
                   api_key=os.getenv("HCAI_API_KEY"),
                   temperature=0.5)

with open(os.path.join(__file__, "..", "prompts", "intake_agent_system_prompt.txt")) as f:
    system_prompt = f.read()

class Symptom(BaseModel):
    name: str = Field(..., description="The name of the symptom")
    severity: str = Field(..., description="The severity of the symptom (e.g., mild, moderate, severe, 10-point scale, etc.)")
    duration: str = Field(..., description="The duration of the symptom (e.g., 3 days, 2 weeks, etc.)")
    location: str = Field(..., description="The location of the symptom (e.g., chest, head, etc.)")
    character: str = Field(..., description="The character of the symptom (e.g., sharp, dull, throbbing, etc.)")
    aggravating_factors : list[str] = Field(..., description="The triggers of the symptom (e.g., exercise, stress, etc.)")
    alleviating_factors : list[str] = Field(..., description="The relievers of the symptom (e.g., rest, medication, etc.)")
    onset: str = Field(..., description="The onset of the symptom (e.g., sudden, gradual, etc.)")
    radiation: str = Field(..., description="The radiation of the symptom (e.g., radiates to arm, back, etc.)")

class PatientInfo(BaseModel):
    name: Optional[str] = Field(..., description="The name of the patient (if provided)")
    age: int = Field(..., description="The age of the patient")
    chief_complaint: str = Field(..., description="The chief complaint of the patient")
    symptoms: list[Symptom] = Field(..., description="The symptoms of the patient")
    pmh: str = Field(..., description="The past medical history of the patient")
    medications: list[str] = Field(..., description="The medications of the patient")
    lifestyle: dict[str, str] = Field(..., description="The lifestyle factors of the patient (e.g., smoking, alcohol use, exercise, etc.)")
    allergies: list[str] = Field(..., description="The allergies of the patient")
    family_history: str = Field(..., description="The family history of the patient")
    red_flags: list[str] = Field(..., description="The red flags of the patient (e.g., shortness of breath, chest pain, etc.)")
    medical_summary: str = Field(..., description="An extensive and detailed summary of the patient's medical information. It MUST BE in Markdown format, structured with headings and bullet points for clarity.")

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
    {"role": "assistant", "content": "What brings you in today?"}
]

print("Assistant: What brings you in today? (Type 'quit' to exit)")

agent.update_state(config=config, values={"messages": messages})

while True:
    user_input = input("Patient: ")
    if user_input.lower() in ["quit", "exit"]:
        break

    try:
        response = agent.invoke({"messages": user_input}, config=config)
                
        tool_called = False
        if "messages" in response:
            for msg in response["messages"]:
                if getattr(msg, "tool_calls", None):
                    for call in msg.tool_calls:
                        if call.get("name") == "end_of_intake":
                            tool_called = True
                            break
        
        if tool_called:
            print("\nAssistant: Thank you for your time. The intake is now complete.")
            break
        
        response["messages"][-1].pretty_print() 

    except Exception as e:
        print(f"\nError: {e}\n")

print("\n--- INTAKE COMPLETE ---")
print("Compiling dense medical summary and structured patient data...\n")

# Use with_structured_output to enforce the PatientInfo format ONLY at the end
structured_model = model.with_structured_output(PatientInfo)

try:
    # We pass the entire conversation history to generate the final structured output
    conversation_state = agent.get_state(config=config)
    final_patient_data = structured_model.invoke(conversation_state.values["messages"])
    print("=== FINAL PATIENT INFO (JSON) ===")
    print(final_patient_data.model_dump_json(indent=2))
    
except Exception as e:
    print(f"\nFailed to generate final report: {e}")

# # Output Specifications
# Your final output for this task is a **Dense Medical Summary**.
# - **Content:** Include EVERY piece of information provided by the patient.
# - **Format:** Use clinical terminology and a professional medical structure
# - **Style:** Synthesize the findings into concise, high-density medical information for a clinician to review.
