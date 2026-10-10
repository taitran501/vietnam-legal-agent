import os
import sys
import gradio as gr

# Ensure src is in python path
sys.path.insert(0, "src")

from dotenv import load_dotenv
load_dotenv(override=True)

# Import the custom FastAPI app with its sleek HTML/Tailwind UI and SSE streaming
from server import app as fastapi_app

# Mount FastAPI app onto Gradio
# When users visit the root URL, they get the custom web UI directly!
demo = gr.mount_gradio_app(fastapi_app, gr.Blocks(), path="/_gradio")

# Entrypoint for Hugging Face Spaces (or local run)
app = fastapi_app

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
