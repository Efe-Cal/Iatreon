import os
from dotenv import load_dotenv

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import RunnableConfig

from ..db.schemas import IntakeProfile
from ..context.processing.pipeline import run_pipeline
from ..context.websearch import web_search, fetch_web_content

load_dotenv()

with open(os.path.join(__file__, "..", "prompts", "research_agent_system_prompt.txt")) as f:
    system_prompt = f.read()

class ResearchAgent:
    def __init__(self):
        self.model = ChatOpenAI(model="gemini-3-flash-preview",
                   base_url="https://ai.hackclub.com/proxy/v1",
                   api_key=os.getenv("HCAI_API_KEY"),
                   temperature=0.7)
        self.checkpointer = InMemorySaver()
        self.config: RunnableConfig = {"configurable": {"thread_id": "2"}}
    
        self.web_search_tool = tool(web_search)
        self.fetch_web_content_tool = tool(fetch_web_content)
        
        self.agent = create_agent(model=self.model,
                                  tools=[self.web_search_tool, self.fetch_web_content_tool, self.search_medical_literature_tool],
                                  system_prompt=system_prompt,
                                  checkpointer=self.checkpointer)
    @tool
    def search_medical_literature_tool(self, query: str, max_articles: int = 5, include_books: bool = False) -> str:
        """
        Run the medical literature search with a given query.
        
        This function orchestrates the entire process of retrieving and processing medical literature based on the input query. It returns a structured dictionary containing the relevant articles and book sections.
        Sources include PubMed, PMC, OpenAlex, and NCBI Bookshelf. The output is normalized and cleaned.
        
        Args:
            query (str): The medical query to search for.
            max_articles (int): The maximum number of articles to retrieve and process.
            include_books (bool): Whether to include book sections from NCBI Bookshelf in the results.
        
        Returns:
            str: A formatted string containing the search results, including relevant articles and book sections.
        """
        
        results = run_pipeline(query, max_articles=max_articles, include_books=include_books)
        articles = results["articles"]
        books = results["books"]

        content = f"Search results for query: '{query}'\n\n"
        for i, article in enumerate(articles, 1):
            content += f"<article_{i}>\n{article.title} ({article.journal}, {article.year}, Citations: {article.citation_count})\nAuthors: {', '.join(article.authors)}\nAbstract: {article.abstract}\n</article_{i}>\n\n"
        
        if books:
            content += f"Relevant Book Sections:\n"
            for i, book in enumerate(books, 1):
                content += f"<book_{i}>\n{book['title']} - {book['section_title']}\nContent: {book['content']}\n</book_{i}>\n\n"

        return content
    
    def run(self, profile: IntakeProfile) -> str:
        user_message = f"""Given the following patient profile, perform research to gather relevant medical information. Use the tools at your disposal to search the web and medical literature for insights related to the patient's chief complaint, symptoms, and red flags. Summarize your findings in a comprehensive report.
# Patient Profile
Chief Complaint: {profile.chief_complaint}
Symptoms: {', '.join(s.name for s in profile.symptoms)}
Red Flags: {', '.join(profile.red_flags)}
Medical Summary: {profile.medical_summary}
"""
        response = self.agent.invoke({"messages": [{"role": "user", "content": user_message}]}, config=self.config)
        return response
