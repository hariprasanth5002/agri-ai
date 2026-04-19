import asyncio
from services.llm_service import LLMService

async def debug_llms():
    llm = LLMService()
    print("--- GEMINI START ---")
    try:
        res1 = await llm._call_gemini("Hello from Gemini")
        print("GEMINI_RES:", res1)
    except Exception as e:
        print("GEMINI_ERR:", e.__class__.__name__, str(e))

    print("--- GROQ START ---")
    try:
        res2 = await llm._call_groq("Hello from Groq")
        print("GROQ_RES:", res2)
    except Exception as e:
        print("GROQ_ERR:", e.__class__.__name__, str(e))

if __name__ == "__main__":
    asyncio.run(debug_llms())
