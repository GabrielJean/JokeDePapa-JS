import requests
import json

# Load config from config.json
with open("config.json", "r") as f:
    config = json.load(f)

gpt_url = config["gpt_url"]
tts_url = config["tts_url"]
api_key = config["api_key"]

# Define the URL and headers
url = "https://www.reddit.com/r/Jokes/top.json?t=week"
headers = {"User-Agent": "Mozilla/5.0"}

def adapt_joke_for_tts(joke_text):
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json"
    }
    data = {
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant. Adapt the following joke for spoken delivery by a TTS system. Make it concise, clear, and suitable for being read aloud with a comic tone. Remove any Reddit formatting or unnecessary text. Do not censor the jokes"
            },
            {
                "role": "user",
                "content": joke_text
            }
        ]
    }
    response = requests.post(gpt_url, headers=headers, json=data)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"].strip()
    else:
        print("GPT adaptation failed:", response.status_code, response.text)
        return joke_text  # fallback to original

def joke_to_tts(joke_text, filename):
    tts_headers = {
        "api-key": api_key,
        "Content-Type": "application/json"
    }
    data = {
        "input": joke_text,
        "model": "gpt-4o-mini-tts",
        "voice": "ash",
        "response_format": "mp3",
        "speed": 1.0,
        "instructions": "Read this joke with a comic tone, as if you are a stand-up comedian."
    }
    response = requests.post(tts_url, headers=tts_headers, json=data)
    if response.status_code == 200:
        with open(filename, "wb") as f:
            f.write(response.content)
        print(f"Saved TTS audio to {filename}")
    else:
        print("TTS request failed:", response.status_code, response.text)

# Fetch jokes and process
response = requests.get(url, headers=headers)
if response.status_code == 200:
    data = response.json()
    posts = data["data"]["children"]

    max_length = 180  # Only process jokes up to 180 characters

    for idx, post in enumerate(posts):
        title = post["data"]["title"]
        selftext = post["data"]["selftext"]
        joke = f"{title}. {selftext}"
        if len(joke.strip()) == 0 or len(joke) > max_length:
            print(f"Skipping (too long or empty): {title}")
            continue
        filename = f"joke_{idx+1}.mp3"
        print(f"Processing: {title}")
        adapted_joke = adapt_joke_for_tts(joke)
        joke_to_tts(adapted_joke, filename)
else:
    print("Failed to fetch data:", response.status_code)