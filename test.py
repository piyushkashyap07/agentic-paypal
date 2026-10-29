import os
import asyncio
from dotenv import load_dotenv
from ollama import AsyncClient

load_dotenv()

async def main():
    api_key = os.getenv("OLLAMA_API_KEY")

    if not api_key:
        raise ValueError("OLLAMA_API_KEY is missing from .env")

    client = AsyncClient(
        host="https://ollama.com",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    response = await client.chat(
        model="gpt-oss:120b",
        messages=[
            {
                "role": "user",
                "content": (
                    "You are running as a model on Ollama Cloud. "
                    "Reply with a short greeting and state your model name."
                ),
            }
        ],
    )

    print("Model response:")
    print(response.message.content)

if __name__ == "__main__":
    asyncio.run(main())