# Iatreon

Iatreon is an AI-doctor platform, aiming to be error-free. It uses LLM agents to get to know the patient and perform deep medical research. The platform is built with a terminal-based user interface using `Textual` and integrates various medical data sources for comprehensive research.

## Features

- **Intake Agent**: Conducts structured patient interviews to gather medical history and current symptoms.
- **Research Agent**: Performs deep medical research by querying scientific databases (NCBI, OpenAlex, PubMed, etc.).
- **TUI Interface**: A terminal-based user interface built with `Textual` for interacting with the platform.
- **Medical Integrations**: Specialized tools for processing medical literature, including ranking and normalization.

## Project Structure

- `agents/`: Core logic for the Intake and Research agents.
- `cli/`: Textual-based terminal interface.
- `context/`: Medical data source integrations and processing pipelines.
- `db/`: Database models and repositories for session management.

## Getting Started

### Prerequisites

- Python 3.10+

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Efe-Cal/Iatreon.git
   cd Iatreon
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Setup Environment Variables
Copy the `.env.example` file to `.env` and fill in your AI API key and other configurations if necessary:
```bash
cp .env.example .env
```

### Running Playwright
To set up Playwright for PDF processing with Docker, run:
```bash
scripts/create_playwright_image.sh  # (.bat for Windows)
scripts/start_playwright_server.sh  # (.bat for Windows)
```

### Running the Application

To start the TUI application:
```bash
python -m cli.cli
```