import os
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import tool

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


agent = create_agent(model=model,
                     tools=[end_of_intake],
                     system_prompt=system_prompt)

messages = [
    {"role": "assistant", "content": "What brings you in today?"}
]

print("Assistant: What brings you in today? (Type 'quit' to exit)")

while True:
    user_input = input("Patient: ")
    if user_input.lower() in ["quit", "exit"]:
        break
    
    messages.append({"role": "user", "content": user_input})
    
    # Run the agent with the updated list of messages
    try:
        response = agent.invoke({"messages": messages})
        
        print(f"\n[DEBUG] Raw response from agent: {response}\n")  # Debugging line to check raw response
        
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

        # Extract output and append to messages for the next turn
        output_text = response.get("output", response.get("messages", [])[-1].content) if isinstance(response, dict) else str(response)
        
        print(f"\nAssistant: {output_text}\n")
        
        messages.append({"role": "assistant", "content": output_text})
        
    except Exception as e:
        print(f"\nError: {e}\n")

print("\n--- INTAKE COMPLETE ---")
print("Compiling dense medical summary and structured patient data...\n")

# Use with_structured_output to enforce the PatientInfo format ONLY at the end
structured_model = model.with_structured_output(PatientInfo)

try:
    # We pass the entire conversation history to generate the final structured output
    final_patient_data = structured_model.invoke(messages)
    print("=== FINAL PATIENT INFO (JSON) ===")
    print(final_patient_data.model_dump_json(indent=2))
    
    # print("\n=== MEDICAL SUMMARY ===")
    # print(final_patient_data.medical_summary)
except Exception as e:
    print(f"\nFailed to generate final report: {e}")
