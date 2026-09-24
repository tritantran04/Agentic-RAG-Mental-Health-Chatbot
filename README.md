# Agentic RAG Mental Health Chatbot

An **Agentic RAG (Retrieval-Augmented Generation) Mental Health chatbot** for medical information retrieval and conversational assistance. The system combines a **Vietnamese medical knowledge base from Vinmec** with **real-time web search** so that the chatbot can answer questions using internal medical documents when relevant and search the Internet when up-to-date information is required.

> **Disclaimer:** This project is intended for educational and information-retrieval purposes. It is not a substitute for diagnosis, treatment, or professional medical advice.

## Overview

The chatbot is designed to answer questions related to:

- Medical conditions and diseases
- Symptoms and common medical information
- Medical treatment and healthcare information available in the knowledge base
- Health-related questions that require current information from the Internet
- General conversational questions without unnecessary tool usage

The system does **not** simply send every question directly to an LLM. Instead, an agent determines which information source should be used:

1. **Internal medical knowledge base** → retrieve relevant Vinmec documents using vector similarity search.
2. **Internet search** → retrieve current information using Tavily when the question requires real-time or newer information, or when the internal knowledge base is insufficient.
3. **Direct LLM response** → used for simple questions such as greetings when external information is unnecessary.

Only **one retrieval/search tool is selected for each query**.

The medical data is collected from the Vinmec website (https://www.vinmec.com/vie/), then structured, normalized, and split into standardized chunks for efficient retrieval in the RAG pipeline

## Architecture

```text
User
  |
  v
Summarize History
  |
  v
LangGraph Agent
  |
  +-----------------------------+-------------------+
  |                             |                    |
  v                             v                    v
 RAG                         Web Search           Direct Answer
(retriever_tool)            (search_web)          (no tool)
  |                             |                    |
  v                             v                    |
Chroma Vector Store          Web Results             |
  |                             |                    |
  +-------------+---------------+                    |
                |                                    |
                v                                    |
        Answer Generation  <-------------------------+
        (Gemini 3 Flash Preview)
                |
                v
          Final Response
```

## Main Components

### 1. LLM

The chatbot uses **Google Gemini 3 Flash Preview** through LangChain:

```text
gemini-3-flash-preview
```

The model is used for tool selection, final answer generation, and summarizing conversation history.

### 2. Agentic Workflow

The agent workflow is implemented with **LangGraph**.

The main workflow is:

```text
START
  -> summarize_history
  -> agent
  -> retrieve OR search_web OR END
  -> generate_answer
  -> END
```

The agent decides whether to call `retriever_tool` or `search_web` based on the user's question.

### 3. Conversation Summarization

Before the agent runs, `summarize_history` checks the accumulated conversation. Instead of cutting the history by a raw message count (which can split a question from its own answer, or from the tool-call/tool-result messages that produced it), it first groups messages into **full turns** — each turn starts at the user's message and ends at the model's final answer (i.e. an `AIMessage` with no pending `tool_calls`). Only whole turns are ever summarized or dropped, so a question and its answer always stay together. A configurable number of the most recent turns (`K_TURNS`) are kept raw; older turns are compressed into a single summary message via the `SUMMARY_HISTORY` prompt, which is prepended back into the conversation state.

### 4. RAG

The repository contains `medical_data.json`, which stores structured medical articles and their text chunks.

The data pipeline in `data.py`:

1. Loads the JSON medical dataset.
2. Converts articles into LangChain `Document` objects.
3. Generates embeddings using:

```text
gemini-embedding-2
```

4. Stores the embeddings in **ChromaDB**.
5. Uses similarity search to retrieve the top 4 relevant documents for a query.

The retriever is implemented as:

```python
vector_store.similarity_search(query, k=4)
```

Retrieved documents include metadata such as article title, category, URL, tags, and chunk information.

### 5. Web Search

The chatbot uses **Tavily Search** for Internet retrieval.

Web search is intended for:

- Current information
- Recent medical information
- Information that may not exist in the internal dataset
- Questions where real-time web sources are useful

The search result URL and content are passed to the answer-generation step.

### 6. Prompts

All system and instruction prompts live in `prompts.py`:

- `SYSTEM_MESSAGE` the main system prompt defining the assistant's role, tool-selection rules, conversation style, and safety rules (e.g. not replacing a real doctor's diagnosis).
- `RETRIEVER_INSTRUCTION` / `SEARCH_WEB_INSTRUCTION` / `NO_TOOL_INSTRUCTION` short task instructions selected in `generate_answer` depending on which tool (if any) was used to answer the current question.
- `SUMMARY_HISTORY` the prompt used by `summarize_history` to compress older conversation turns into a concise summary.

### 7. Conversation Memory

The LangGraph workflow uses `MemorySaver` to maintain conversation state by thread.

The current configuration uses a single, hardcoded thread ID:

```python
config = {"configurable": {"thread_id": "user_1"}}
```

This allows the graph to maintain conversation state across requests during execution, but note that **all users currently share the same thread (`"user_1"`)** — the app is effectively single-session. Supporting multiple concurrent users would require generating a distinct `thread_id` per user/session instead of using a fixed value.

## Project Structure

```text
Mental-Health-Chatbot/
│
├── agent.py              # LangGraph agent, tools and workflow
├── data.py               # Medical data loading and ChromaDB setup
├── prompts.py            # System prompt, tool-instruction prompts, summary prompt
├── medical_data.json     # Vinmec data
├── requirements.txt      # Python dependencies
└── README.md
```

## Technologies

- **Python**
- **LangChain**
- **LangGraph**
- **Google Gemini 3 Flash Preview**
- **Google Generative AI Embeddings**
- **ChromaDB**
- **Tavily Search**
- **RAG (Retrieval-Augmented Generation)**
- **Agentic Workflow / Tool Calling**

## Requirements

Recommended environment:

- Python 3.10+
- Google Gemini API key
- Tavily API key
- Sufficient disk space for the local Chroma vector database

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/tritantran04/Agentic-RAG-Mental-Health-Chatbot.git
cd Mental-Health-Chatbot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

## Environment Variables

Create a `.env` file in the project root:

```env
GOOGLE_API_KEY=your_google_gemini_api_key
TAVILY_API_KEY=your_tavily_api_key
```

Do **not** commit the `.env` file or expose API keys publicly.

## Run the Chatbot

### 1. Build the vector database (first run only)

Make sure `medical_data.json` is present in the project root, then run:

```bash
python data.py
```

This loads and chunks the medical data, generates embeddings with `gemini-embedding-2`, and persists them to the local ChromaDB directory configured by `persist_dir` in `data.py`. On later runs, if the collection already contains documents, this step is skipped automatically and the existing database is reused.

> **Note:** `persist_dir` in `data.py` is currently a hardcoded local path. Update it to match your own machine before running.

### 2. Start the chatbot

```bash
python agent.py
```

This starts an interactive command-line loop. Type your question and press Enter; type `exit` or `end` to quit.

Example user query:

```text
Trầm cảm có những triệu chứng phổ biến nào?
```

The processing flow is approximately:

```text
User Question
     |
     v
LangGraph Agent
     |
     v
Medical question?
     |
     v
retriever_tool
     |
     v
Chroma similarity search (top 4)
     |
     v
Relevant Vinmec documents
     |
     v
Gemini 3 Flash Preview
     |
     v
Final answer
```

For a query requiring current information, for example:

```text
Có thông tin y tế mới nào liên quan đến ...?
```

the agent can select `search_web` instead:

```text
User Question
     |
     v
LangGraph Agent
     |
     v
search_web
     |
     v
Tavily Search
     |
     v
Web Results
     |
     v
Gemini 3 Flash Preview
     |
     v
Final answer
```

## Key Features

- **Agentic tool selection** using LangGraph
- **RAG-based medical question answering** using Vinmec documents
- **Vector similarity search** with ChromaDB
- **Semantic embeddings** using Google's `gemini-embedding-2`
- **Real-time web search** through Tavily
- **LLM tool calling** for dynamic retrieval decisions
- **Conversation state management** with LangGraph `MemorySaver`
- **Turn-aware history summarization**, compressing older conversation turns without splitting a question from its own answer
- **Source-aware retrieval**, preserving document metadata and web URLs

## Limitations

- The quality of answers depends on the quality and coverage of the Vinmec dataset and retrieved web results.
- Web search depends on Tavily availability and Internet access.
- The current ChromaDB persistence path is configured in `data.py` and may need to be changed for another machine/environment.
- The chatbot currently uses a single hardcoded `thread_id` (`"user_1"`), so conversation memory is shared across all users rather than isolated per user/session.
- The project is a prototype for learning and research and should not be used as a medical diagnostic system.

## Author
**Tran Tri Tan**
