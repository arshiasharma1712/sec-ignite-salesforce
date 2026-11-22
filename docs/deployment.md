# Deploy on Vercel

This is a Streamlit server. Vercel's Container runtime builds the root `Dockerfile`; `vercel.json` explicitly selects that framework. The image runs Python 3.12 with the tested Streamlit 1.67.0 and pandas 3.1.1, listening on Vercel's default port 80 (or `PORT` when configured).

Import the repository's `main` branch in Vercel, or upload a clean source archive containing `Dockerfile`, `.dockerignore`, `.vercelignore`, `vercel.json`, `app.py`, `src/*.py`, `data/*.csv`, and `.streamlit/config.toml`. The root directory is `.`. No separate build-command or output-directory override is needed. A direct upload does not connect GitHub; connect the repository later for automatic deployments.

Set `GEMINI_API_KEY` in the project's server environment variables to enable chat, then redeploy. `GEMINI_MODEL` is optional. Never upload `.streamlit/secrets.toml`, `.env` files, a virtual environment, or Git history. The Docker build copies only runtime files, and `.dockerignore` excludes everything else.

Validate the live URL by running Sample and Scale, opening lead/rep dialogs, asking the assistant a question, and resetting. Each browser session holds its own temporary results and manager changes. Vercel connections have a maximum duration and reconnects may reach another instance, so in-memory results/chat can be lost on reconnect or instance replacement. Download results before closing or refreshing; this deployment does not add durable storage.

References: [Container runtime](https://vercel.com/docs/functions/runtimes/container), [WebSocket lifecycle](https://vercel.com/docs/functions/websockets).

## Validation

The clean upload archive was extracted into a temporary directory and run through Streamlit AppTest on macOS arm64 / Python 3.12.14 / Streamlit 1.67.0 / pandas 3.1.1. Sample produced 100 outcomes (9 assigned, 91 reviewed); Scale produced 50,000 outcomes (40,665 assigned, 9,335 reviewed); Reset cleared the results. Chat was correctly disabled without credentials. The archive contains no secrets or Git history. Docker is not installed locally, so the container build and hosted smoke check must be completed in Vercel before considering deployment validated.
