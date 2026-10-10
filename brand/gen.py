"""Generate Vigil brand images with OpenAI's image API (key from ../.env)."""
import base64, json, os, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

for line in Path(__file__).resolve().parent.parent.joinpath(".env").read_text().splitlines():
    k, _, v = line.partition("=")
    os.environ.setdefault(k.strip(), v.strip())

def gen(name, prompt, size="1024x1024", background="transparent", quality="high", model="gpt-image-2"):
    body = {"model": model, "prompt": prompt, "size": size, "quality": quality, "n": 1}
    if background:
        body["background"] = background
    req = urllib.request.Request("https://api.openai.com/v1/images/generations", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"})
    try:
        out = json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        return f"{name}: {e.code} {e.read().decode()[:300]}"
    Path(name).write_bytes(base64.b64decode(out["data"][0]["b64_json"]))
    return f"{name}: ok"

if __name__ == "__main__":
    jobs = json.load(open(sys.argv[1]))
    with ThreadPoolExecutor(6) as ex:
        for r in ex.map(lambda j: gen(**j), jobs):
            print(r, flush=True)
