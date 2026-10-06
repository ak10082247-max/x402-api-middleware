from fastapi import FastAPI
import uvicorn
import os

app = FastAPI(title="Mock Target Backend")

@app.get("/weather")
def get_weather():
    return {"city": "San Francisco", "temperature": "22°C", "condition": "Sunny"}

@app.post("/data")
def post_data(payload: dict):
    return {"status": "success", "received": payload}

if __name__ == "__main__":
    port = int(os.environ.get("MOCK_PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
