from pydantic import BaseModel, Field
from typing import Optional

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
