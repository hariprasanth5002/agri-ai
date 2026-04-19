import asyncio
from services.llm_service import LLMService
import os

from dotenv import load_dotenv
load_dotenv()

async def test():
    llm = LLMService()
    try:
        print('Gemini API KEY:', os.getenv("GEMINI_API_KEY")[:4] if os.getenv("GEMINI_API_KEY") else None)
        print('Gemini:', await llm._call_gemini('Hello'))
    except Exception as e:
        print("Gemini Exception", e)
    try:
        print('Groq API KEY:', os.getenv("GROQ_API_KEY")[:4] if os.getenv("GROQ_API_KEY") else None)
        print('Groq:', await llm._call_groq('Hello'))
    except Exception as e:
        print("Groq Exception", e)

if __name__ == "__main__":
    asyncio.run(test())
