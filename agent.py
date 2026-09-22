from dotenv import load_dotenv
import operator
import datetime
from typing import Annotated, List, Literal, TypedDict
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, RemoveMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain.tools import tool
from langchain_tavily import TavilySearch
from langgraph.checkpoint.memory import MemorySaver
from data import vector_store
import prompts
load_dotenv()

# Install llm 
llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", temperature=0)

# Memory
memory = MemorySaver()  
   
# Class message
class MessagesState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]

# Get last context
def get_latest_tool_context(state: MessagesState):
    for msg in reversed(state["messages"]):
        if (hasattr(msg, 'type') and msg.type == "tool"):
            return msg.content, msg.name 
    return None, None

def split_into_turns(messages):
    """
    Gom messages thành từng lượt hỏi đáp bao gồm:
    - câu hỏi của người dùng
    - câu trả lời của AI
    - message gọi tool
    """
    turns, current = [], []
    for m in messages:
        if isinstance(m, HumanMessage) and current:
            turns.append(current)
            current = [m]
        else:
            current.append(m)
        if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
            turns.append(current)
            current = []
    if current:
        turns.append(current)
    return turns

# Get message's text
def get_text(m) -> str:
    content = m.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            item.get("text", "") for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""

# Summarize History
K_TURNS = 1
def summarize_history(state: MessagesState):
    messages = state["messages"]
    turns = split_into_turns(messages)

    if len(turns) <= K_TURNS:
        return {}

    old_turns, keep_turns = turns[:-K_TURNS], turns[-K_TURNS:]
    old  = [m for t in old_turns  for m in t]
    keep = [m for t in keep_turns for m in t]

    history_text = "\n".join(
        f"{'human' if isinstance(m, HumanMessage) else 'ai'}: {get_text(m)}"
        for m in old
        if isinstance(m, (HumanMessage, AIMessage))
        and not (isinstance(m, AIMessage) and getattr(m, "tool_calls", None))
        and get_text(m)
    )
    summary_resp = llm.invoke([
        SystemMessage(content=prompts.SUMMARY_HISTORY),
        HumanMessage(content=history_text)
    ])
    summary_text = summary_resp.content[0]["text"]

    summary_msg = HumanMessage(content=f"[Tóm tắt hội thoại trước đó]: {summary_text}")
    delete = [RemoveMessage(id=m.id) for m in messages]
    return {"messages": delete + [summary_msg] + keep}

system_message = SystemMessage(content=prompts.SYSTEM_MESSAGE)

# Decision
def agent_node(state: MessagesState):
    llm_with_tools = llm.bind_tools([retriever_tool, search_web])
    response = llm_with_tools.invoke([system_message] + state["messages"])
    return {"messages": [response]}

# Answer
def generate_answer(state: MessagesState):
    user_messages = [m for m in state["messages"] if isinstance(m, HumanMessage) or (isinstance(m, dict) and m.get('role') == 'user')]
    latest_question = user_messages[-1].content if hasattr(user_messages[-1], 'content') else user_messages[-1].get('content', '')

    context, tool_name = get_latest_tool_context(state)
    
    if tool_name == "search_web":
        instruction = prompts.SEARCH_WEB_INSTRUCTION
    elif tool_name == "retriever_tool":
        instruction = prompts.RETRIEVER_INSTRUCTION
    else:
        instruction = prompts.NO_TOOL_INSTRUCTION
        
    gen_prompt = f"""
    NHIỆM VỤ: {instruction}
    NGỮ CẢNH HIỆN TẠI: {context}
    CÂU HỎI HIỆN TẠI: {latest_question}
    """
    
    response = llm.invoke([
        system_message,
        HumanMessage(content=gen_prompt)
    ])
    return {"messages": [response]}

# Tool retrieve
@tool()
def retriever_tool(query: str):
    """
    Truy xuất thông tin từ vector database
    Dùng kiến thức có sẵn để trả lời
    
    Args:
        query: câu truy vấn để tìm kiếm trong vector database.
    """
    retrieved_docs = vector_store.similarity_search(query, k=4)

    serialized = "\n\n".join(
        (
            f"Source: {doc.metadata}\n"
            f"Content: {doc.page_content}"
        )
        for doc in retrieved_docs
    )
    return serialized, retrieved_docs


# Tool search_web
tavily_tool = TavilySearch(
    max_results=1,
)

@tool
def search_web(query: str) -> str:
    """
    Tìm thêm thông tin từ internet khi thông tin từ vector database là không đủ
    
    Args:
        query: câu truy vấn để search web.
    """
    now = datetime.datetime.now()
    current_time_info = f"ngày {now.strftime('%d/%m/%Y')} (Giờ {now.strftime('%H:%M')})"
    
    enhanced_query = f"{query} (Ngày hiện tại: {current_time_info})"
    
    rall = tavily_tool.invoke(enhanced_query)
    results = rall.get("results")
    
    formatted_results = []
    for res in results:
        url = res.get('url')
        content = res.get('content')
        formatted_results.append(f"Source: {url}\nContent: {content}")

    return "\n\n".join(formatted_results)

# Route
def route_decision(state: MessagesState) -> Literal["retrieve", "search_web", "end"]:
    last_message = state["messages"][-1]
    
    if not last_message.tool_calls:
        return "end"
    
    tool_name = last_message.tool_calls[0]["name"]
    if tool_name == "retriever_tool":
        return "retrieve"
    else:
        return "search_web"


# Create graph
workflow = StateGraph(MessagesState)
workflow.add_node("summarize_history", summarize_history)
workflow.add_node("agent", agent_node)
workflow.add_node("retrieve", ToolNode([retriever_tool]))
workflow.add_node("search_web", ToolNode([search_web]))
workflow.add_node("generate_answer", generate_answer)


# Add edge
workflow.add_edge(START, "summarize_history")
workflow.add_edge("summarize_history", "agent")
workflow.add_conditional_edges(
    "agent",
    route_decision,
    {
        "retrieve": "retrieve",
        "search_web": "search_web",
        "end": END
    }
)
workflow.add_edge("retrieve", "generate_answer")
workflow.add_edge("search_web", "generate_answer")
workflow.add_edge("generate_answer", END)
#compile
graph = workflow.compile(checkpointer=memory)

# Config user and thread
config = {"configurable":{"thread_id":"user_1"}}


if __name__ == '__main__':
    # Test Chatbot
    print("|____|____|____-___ HELLO MY FRIEND ___-____|____|____|")
    while True:
        
        user_input = input("You: ")
        if user_input.lower() in ["exit","end"]:
            break
        if not user_input.strip():         
            continue
        
        for m in graph.stream(
            {"messages": [HumanMessage(content=user_input)]},
            config,
            stream_mode='updates'
        ):
            
            # for node_name, node_message in m.items():
            #     print(f"{node_name}: {node_message}\n")
        
            for node_name, node_output in m.items():
                    if not node_output:  
                        continue
                    msg = node_output["messages"][-1]
                    if isinstance(msg, AIMessage) and msg.content:
                        print(f"Bot: {msg.content[0]['text']}")
                        print("\n========================================================================================================")
 
        