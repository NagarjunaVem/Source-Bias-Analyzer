import requests
import json
import re

OLLAMA_URL = "http://localhost:11434/api/generate"


def load_prompt(text):
    with open("app/prompts/bias_prompt.txt", "r", encoding="utf-8") as f:
        template = f.read()
    return template.replace("{article}", text)


def extract_json(text):
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return match.group() if match else None


def analyze_bias(text):
    prompt = load_prompt(text)

    response = requests.post(
    OLLAMA_URL,
    json={
        "model": "llama3:8b",
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 500   \
        }
    }
)

    raw_output = response.json()["response"]
    clean_json = extract_json(raw_output)

    try:
        return json.loads(clean_json)
    except:
        return {
            "error": "Invalid JSON",
            "raw_output": raw_output
        }

