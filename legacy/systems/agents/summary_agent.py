# systems/agents/summarization/summary_agent.py

from langchain_core.messages import HumanMessage, AIMessage
from systems.agents.tools.llm_config import config

# Load LLM just for summarization
summary_llm = config.get_llm("tool_use")

def summarize_conversation(state):
    """
    Summarize the troubleshooting conversation into a clean, concise form
    without headers or footers.
    """

    print("\n✨ Summarizing the conversation...")

    # Extract the conversation history
    conversation_text = "\n".join([m.content for m in state['messages']])

    # Ask the LLM to summarize it
    summary = summary_llm.invoke([
        HumanMessage(content=f"Summarize this troubleshooting conversation in a clear and concise form suitable to be passed to a knowledge retrieval agent:\n{conversation_text}\n\nJust include the problem description, attempted resolutions, and important context. No header, no footer.")
    ])

    return {
        "messages": state["messages"] + [AIMessage(content="\n--- Conversation Summary ---\n" + summary.content)],
        "tries": state["tries"],
        "video_path": None,
        "summary_for_retrieval": summary.content.strip()
    }
