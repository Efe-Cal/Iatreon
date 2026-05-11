import os
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI

from langchain.messages import HumanMessage, AIMessage


load_dotenv()


patient_model = ChatOpenAI(model="gemini-2.5-flash-lite",
                   base_url="https://ai.hackclub.com/proxy/v1",
                   api_key=os.getenv("HCAI_API_KEY"),
                   temperature=1)


def mock_patient_response(messages):
    messages.pop(0)
    messages.insert(0, {"role": "system", "content": """You are a patient providing information to a medical intake agent. Make up a realistic medical scenario, including symptoms, medical history, lifestyle factors, and any other relevant information. Answer the agent's questions in a way that is consistent with your scenario. USE PLAIN TEXT WITH NO FORMATTING OR STRUCTURE. DO NOT PROVIDE ANY INFORMATION UNLESS ASKED BY THE AGENT. \nBE CONCISE. ACT LIKE A REAL PATIENT. DO NOT OFFER ANY ADDITIONAL INFORMATION OR CLARIFICATIONS UNLESS ASKED."""})
    for i, msg in enumerate(messages):
        if type(msg) == dict:
            if msg["role"] == "assistant":
                msg["role"] = "user"
            if msg["role"] == "user":
                msg["role"] = "assistant"
        else:
            if type(msg) == HumanMessage:
                messages[i] = {"role": "assistant", "content": msg.content}
            elif type(msg) == AIMessage:
                messages[i] = {"role": "user", "content": msg.content}

    return patient_model.invoke(input=messages).content