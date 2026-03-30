import json
import logging
import numpy as np
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("queue_embedder")

# We completely isolate the safe embedding logic, completely ignoring any FAISS dependencies
try:
    from app.embeddings.chunker import chunk_text
    from app.embeddings.embed import get_embeddings_batch
except ImportError as e:
    logger.error(f"Missing AI dependencies for Embedding script: {e}")
    chunk_text = None
    get_embeddings_batch = None

async def process_cycle_embeddings(cycle_folder: Path, output_base: Path) -> bool:
    """
    Reads a scraped cycle folder, chunks the text, computes raw vector embeddings, 
    and saves them independently in data/cycle_embeddings/ without triggering FAISS.
    """
    if not chunk_text or not get_embeddings_batch:
        logger.error("Embedding tools unavailable due to missing pip packages. Cycle folder deferred.")
        return False
        
    print(f"\n\033[1;35m{'='*70}\033[0m")
    print(f"\033[1;35m🧠 [EMBEDDINGS GENERATOR] Processing {cycle_folder.name}...\033[0m")
    print(f"\033[1;35m{'='*70}\033[0m\n")
    
    # 1. Gather all unique JSON files from this cycle
    all_json_files = []
    for source_dir in (cycle_folder / "web", cycle_folder / "rss"):
        if source_dir.exists():
            all_json_files.extend(list(source_dir.glob("*.json")))
            
    if not all_json_files:
        logger.info("No JSON articles found to embed.")
        return True
        
    # 2. Extract and chunk the text
    metadata_records = []
    text_chunks = []
    
    for json_file in all_json_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
                
            for article in data:
                content = str(article.get("content") or article.get("text") or "").strip()
                if not content:
                    continue
                    
                chunks = chunk_text(content)
                for i, chunk in enumerate(chunks):
                    text_chunks.append(chunk)
                    metadata_records.append({
                        "article_id": article.get("id", ""),
                        "url": article.get("url", ""),
                        "source": article.get("source", json_file.stem),
                        "chunk_id": i,
                        "text": chunk
                    })
        except Exception as e:
            logger.error(f"Failed parsing {json_file.name} for embeddings: {e}")
            
    if not text_chunks:
        print("No viable text chunks discovered in this cycle.")
        return True
        
    # 3. Call Ollama (The Embeddings API)
    print(f"Sending {len(text_chunks)} text chunks to LangChain Ollama Embeddings...")
    try:
        raw_vectors = get_embeddings_batch(text_chunks)
    except Exception as e:
        logger.error(f"Ollama Embedding completely failed during batch processing: {e}")
        return False
        
    # 4. Save the pure `.npy` and metadata to disk for your friend to easily pick up!
    save_dir = output_base / "cycle_embeddings" / cycle_folder.name
    save_dir.mkdir(parents=True, exist_ok=True)
    
    metadata_path = save_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata_records, indent=2, ensure_ascii=False), encoding="utf-8")
    
    vectors_path = save_dir / "embeddings.npy"
    np.save(vectors_path, raw_vectors)
    
    print(f"\033[1;32m✅ Successfully generated and saved {len(raw_vectors)} vectors locally inside {save_dir.relative_to(output_base)}\033[0m")
    return True
