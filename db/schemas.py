from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional

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

class IntakeProfile(BaseModel):
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

class DifferentialItem(BaseModel):
    condition: str
    likelihood: Literal["primary", "possible", "unlikely_but_considered"]
    supporting_evidence: list[str] = Field(default_factory=list)
    against_evidence: list[str] = Field(default_factory=list)
 
 
class DiagnosisReport(BaseModel):
    primary_diagnosis: str
    confidence: Literal["high", "moderate", "low"]
    differential: list[DifferentialItem] = Field(default_factory=list)
    reasoning_summary: str = Field(
        description="Short clinical reasoning narrative tying evidence to conclusion"
    )
    recommended_next_steps: list[str] = Field(default_factory=list)
    red_flags_to_monitor: list[str] = Field(
        default_factory=list, description="Symptoms that should trigger urgent care if they appear"
    )

class ArticleData(BaseModel):
    pubmed_id: Optional[str] = Field(None, description="The PubMed ID for the article, if available")
    pmc_id: Optional[str] = Field(None, description="The PMC ID for the article, if available")
    doi: Optional[str] = Field(None, description="The DOI for the article, if available")
    openalex_id: Optional[str] = Field(None, description="The OpenAlex ID for the article, if available")
    title: str = Field(..., description="The title of the article")
    abstract: Optional[str] = Field(None, description="The abstract of the article")
    full_text: Optional[str] = Field(None, description="The full text of the article (if available)")
    pdf_url: Optional[str] = Field(None, description="The PDF URL of the article (if available)")
    authors: list[str] = Field(default_factory=list, description="The authors of the article")
    journal: Optional[str] = Field(None, description="The journal of the article")
    year: Optional[int] = Field(None, description="The publication year of the article")
    study_type: Optional[str] = Field(None, description="The type of the study (e.g., RCT, observational, review, etc.)")
    keywords: list[str] = Field(default_factory=list, description="Keywords associated with the article")
    mesh_terms: list[str] = Field(default_factory=list, description="MeSH terms associated with the article")
    citation_count: Optional[int] = Field(None, description="The number of citations of the article")
    quality_score: Optional[float] = Field(None, description="The quality score assigned to the article")
    full_text_available: bool = Field(False, description="Whether the article has full text available")
    source: Optional[str] = Field(None, description="The source that produced the article record")

class BookSectionData(BaseModel):
    accession_id: str = Field(..., description="The NCBI Bookshelf accession ID for the book section")
    title: str = Field(..., description="The title of the book")
    source: str = Field(..., description="The source that produced the book section record")
    text: str = Field(..., description="The full text of the book section")
    url: Optional[str] = Field(None, description="The URL of the book section (if available)")
    full_text_available: bool = Field(True, description="Whether the full text of the book section is available")
    
class UserProfileData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    demographics: dict[str, str] = Field(..., description="The demographic information of the user (e.g., age, gender, etc.)")
    pmh: list[str] = Field(..., description="The past medical history of the user")
    medications: list[str] = Field(..., description="The medications of the user")
    allergies: list[str] = Field(..., description="The allergies of the user")
    family_history: list[str] = Field(..., description="The family history of the user")
    social: dict[str, str] = Field(..., description="The social history of the user (e.g., smoking, alcohol use, exercise, etc.)")
    medical_summary: Optional[str] = Field(None, description="A summary of the user's medical information")
