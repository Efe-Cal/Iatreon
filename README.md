# Iatreon

Iatreon is an AI-doctor platform, aiming to be error-free. It uses LLM agents to get to know the patient and perform deep medical research. The platform is built with a terminal-based user interface using Bubble Tea and integrates various medical data sources for comprehensive research.

## Features

- **Intake Agent**: Conducts structured patient interviews to gather medical history and current symptoms.
- **Research Agent**: Performs deep medical research by querying scientific databases (NCBI, OpenAlex, PubMed, etc.).
- **TUI Interface**: A terminal-based user interface built with `Bubble Tea` for interacting with the platform.
- **Medical Integrations**: Specialized tools for processing medical literature, including ranking and normalization.

## Project Structure

- `agents/`: Core logic for the Intake and Research agents.
- `tui/`: Bubble Tea-based terminal interface.
- `context/`: Medical data source integrations and processing pipelines.
- `db/`: Database models and repositories for session management.
- `api/`: FastAPI application for serving the TUI and handling requests.
- `pdf_worker/`: Background worker for handling PDF downloads and processing.

## Getting Started

### How to Run Locally

1. Clone the repository:
   ```bash
   git clone https://github.com/Efe-Cal/Iatreon.git
   cd Iatreon
   ```
2. Run the Docker Compose setup
   ```bash
   docker compose up
   ```
3. Set up SSH agent forwarding:
   ```bash
   ./scripts/setup-iatreon.sh --no-connect
   ```
   On Windows PowerShell:
   ```powershell
   .\scripts\setup-iatreon.ps1 -NoConnect
   ```
4. Access the TUI interface with SSH:
   ```bash
   ssh iatreon
   ```

For production, set `TUI_SSH_PORT=22` before running Docker Compose.

### Development Setup

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

### Running the Backend and PDF Worker in Docker
Build and start the authenticated backend, private PDF API, Redis, and RQ worker together:
```bash
docker compose up --build backend-api pdf-api pdf-worker
```

The backend listens on port `8787` and uses a private PostgreSQL service. The PDF API is bound to `127.0.0.1:8000` for local debugging, Redis has no host port, and the worker writes downloaded files to the shared `downloads` volume.
