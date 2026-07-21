# Iatreon

Iatreon is an privacy-first AI-doctor platform, aiming to be error-free. It uses AI agents to get to know the patient and perform deep medical research. The platform is built with a terminal-based user interface using Bubble Tea and integrates various medical data sources for comprehensive research.

## Features

- **Intake Agent**: Conducts structured patient interviews to gather medical history and current symptoms.
- **Research Agent**: Performs deep medical research by querying scientific databases (NCBI, OpenAlex, PubMed, etc.).
- **Diagnosis Agent**: Analyzes patient data and research findings to provide potential diagnoses and treatment options.
- **THE Doctor**: A specialized agent that is equipped to handle your queries and summon the other agents as needed for comprehensive medical analysis.
- **Patient Profile Building**: Constructs and continuously updates a detailed patient profile based on the intake interview and research findings.
- **TUI Interface**: A terminal-based user interface built with `Bubble Tea` for interacting with the platform.
- **Medical Integrations**: Specialized tools for processing medical literature; including scraping, ranking and normalization.

## Privacy and Security

Iatreon is designed around privacy and security. Your data is stored in a local encrypted database, and it only leaves your machine when you use external AI providers. Iatreon does not store any personal data on external servers. Even when you backup your database, it remains encrypted.

## Project Structure

- `agents/`: Core logic for the Intake and Research agents.
- `tui/`: Bubble Tea-based terminal interface.
- `context/`: Medical data source integrations and processing pipelines.
- `db/`: Database models and repositories for session management.
- `legacy_api/`: (Deprecated) FastAPI application for serving the TUI and handling requests.
- `pdf_worker/`: Background worker for handling PDF downloads and processing.
- `local_worker/`: Local worker that handles your LLM calls, orchestrates the agents, and manages your encrypted database.

## Installation
1. Download the latest release from the [Releases](https://github.com/Efe-Cal/Iatreon/releases) page.  
2. Run the installer and follow the prompts to complete the installation.

---

### Development Setup

#### Setup for Python Worker
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


#### Setup for TUI
1. Navigate to the `tui` directory:
   ```bash
   cd tui
   ```
2. Install dependencies:
   ```bash
   go mod tidy
   ```
3. Set the `APP_ENV` environment variable to `dev` for local development:
   ```bash
   export APP_ENV=dev  # On Windows: set APP_ENV=dev
   ```

#### How to Build for Prod
Run the build.ps1 script to build the project and produce an installer:
```powershell
.scripts\build.ps1
```

### Setup Environment Variables
Copy the `.env.example` file to `.env` and fill in your AI API key and other configurations if necessary:
```bash
cp .env.example .env
```

### Running the Backend and PDF Worker in Docker
Build and start the authenticated backend, private PDF API, Redis, and RQ worker together:
```bash
docker compose up --build backend-api pdf-api pdf-worker
```

The backend listens on port `8787` and uses a private PostgreSQL service. The PDF API is bound to `127.0.0.1:8000` for local debugging, Redis has no host port, and the worker writes downloaded files to the shared `downloads` volume.
