"""RAG System MCP Server — exposes RAG tools to MCP-compatible clients."""
import os
import httpx
from fastmcp import FastMCP

RAG_PROXY_URL = os.getenv("RAG_PROXY_URL", "http://localhost:8080")

mcp = FastMCP(
    "RAG System",
    instructions="Corporate Knowledge Assistant — search and chat with your organization's documents",
)

@mcp.tool()
async def rag_search(query: str, limit: int = 5) -> str:
    """Search corporate knowledge base for relevant documents.
    
    Args:
        query: Natural language search query
        limit: Maximum number of results to return (default: 5)
    
    Returns:
        Search results with document excerpts and relevance scores
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RAG_PROXY_URL}/v1/chat/completions",
            json={
                "model": "rag",
                "messages": [{"role": "user", "content": f"Search: {query}"}],
                "stream": False,
                "rag_search_only": True,
            },
            timeout=30.0,
        )
        return response.json()["choices"][0]["message"]["content"]

@mcp.tool()
async def rag_chat(message: str, context: str = "") -> str:
    """Chat with the RAG system — ask questions about corporate knowledge.
    
    Args:
        message: Your question or message
        context: Optional additional context to include
    
    Returns:
        AI-generated answer based on corporate knowledge base
    """
    messages = [{"role": "user", "content": message}]
    if context:
        messages.insert(0, {"role": "system", "content": f"Context: {context}"})
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RAG_PROXY_URL}/v1/chat/completions",
            json={
                "model": "rag",
                "messages": messages,
                "stream": False,
            },
            timeout=60.0,
        )
        return response.json()["choices"][0]["message"]["content"]

@mcp.tool()
async def rag_feedback(query: str, answer: str, rating: str, correction: str = "") -> str:
    """Submit feedback on RAG system answers to improve quality.
    
    Args:
        query: The original query
        answer: The answer that was given
        rating: "positive" or "negative"
        correction: Optional correction if rating is negative
    
    Returns:
        Confirmation message
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RAG_PROXY_URL}/v1/feedback",
            json={
                "query": query,
                "answer": answer,
                "rating": rating,
                "correction": correction,
            },
            timeout=10.0,
        )
        return "Feedback submitted successfully"

@mcp.resource("rag://collections")
async def list_collections() -> str:
    """List available document collections in the RAG system."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{RAG_PROXY_URL}/v1/models", timeout=10.0)
        return str(response.json())

@mcp.prompt()
def rag_help() -> str:
    """Get help on using the RAG system tools."""
    return """
Available RAG tools:
- rag_search(query, limit) — Search corporate documents
- rag_chat(message, context) — Ask questions about corporate knowledge
- rag_feedback(query, answer, rating, correction) — Submit feedback

For best results:
- Be specific in your queries
- Use rag_search first to find relevant documents
- Use rag_chat to ask questions about those documents
- Submit feedback to improve answer quality
"""

if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.run(transport="http", host="0.0.0.0", port=3000)
    else:
        mcp.run(transport="stdio")
