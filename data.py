#load file json data
import json
from typing import List
# from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import os
from dotenv import load_dotenv
import time
import hashlib
from google.genai.errors import ClientError


load_dotenv()
json_path = "medical_data.json"

def load_data_doc(path: str) -> List[Document]:
    """
    File có dạng:
    [
      {
        "article": { "title": ..., "category": ..., "url": ..., "tags": (..) },
        "chunks": [
          {"chunk_id": 0, "text": "...", "subcategories": [...]},
          ...
        ]
      },
      ...
    ]
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    docs: List[Document] = []
    for item in data:
        article = item.get("article", {})
        chunks = item.get("chunks", [])

        base_meta = {
            "title": article.get("title",""),
            "category": article.get("category", ""),
            "url": article.get("url",""),
            "tags": article.get("tags",""),
        }    

        for ch in chunks:
            text = ch.get("text","")
            if not text.strip():
                continue
            
            meta = base_meta.copy()
            meta["chunk_id"] = ch.get("chunk_id")
            meta["subcategories"] = ch.get("subcategories,()")
            docs.append(Document(page_content=text, metadata=meta))

    print(f"Load {len(docs)} Vinmec chunks Documents")
    return docs

docs = load_data_doc(json_path)

for doc in docs:
    if "tags" in doc.metadata and isinstance(doc.metadata["tags"], list):
        doc.metadata["tags"] = ", ".join(doc.metadata["tags"])

all_splits = docs

embeddings = GoogleGenerativeAIEmbeddings(
    model="gemini-embedding-2",
    dimension=768,
)

persist_dir = "D:/My Project/Medical Chatbot/Agentic-RAG-agent-chatbot-main/chroma_db"
collection_name = "mental_health"


vector_store = Chroma(
    collection_name=collection_name,
    embedding_function=embeddings,
    persist_directory=persist_dir,
)
    
# vector_store.add_documents(all_splits)
# print(f"Successfully added {len(all_splits)} documents to Chroma.")
    
BATCH_SIZE = 30
SLEEP_SECONDS = 35
MAX_RETRY = 5

if vector_store._collection.count() == 0:
    print(f"Create chroma db, embed {len(all_splits)} docs")
    ids = [hashlib.sha256(d.page_content.encode("utf-8")).hexdigest() for d in all_splits]

    for i in range(0, len(all_splits), BATCH_SIZE):
        batch_docs, batch_ids = all_splits[i : i + BATCH_SIZE], ids[i : i + BATCH_SIZE]
        done = vector_store.get(ids=batch_ids)["ids"]
        todo = [(d, _id) for d, _id in zip(batch_docs, batch_ids) if _id not in done]
        if not todo:
            continue

        for attempt in range(1, MAX_RETRY + 1):
            try:
                vector_store.add_documents([d for d, _ in todo], ids=[i for _, i in todo])
                break
            except ClientError as e:
                if getattr(e, "status", "") != "RESOURCE_EXHAUSTED" or attempt == MAX_RETRY:
                    raise
                print(f"  [429] for {20 * attempt}s, try again (lan {attempt})...")
                time.sleep(20 * attempt)
        time.sleep(SLEEP_SECONDS)

    print(f"Completed! {vector_store._collection.count()} docs in DB")
else:
    print(f"Load chroma db (Available {vector_store._collection.count()} docs)")