import asyncio
import json
import base64
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn
from dotenv import load_dotenv

from google.adk.runners import Runner
from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv()

app = FastAPI(title="EduMentor Live - AI Backend")
APP_NAME = "edumentor-live"

session_service = InMemorySessionService()

agent = Agent(
    name="edumentor_agent",
    model=os.getenv("AGENT_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"),
    instruction=(
        "You are EduMentor, an elite, real-time AI Study and Career Companion. "
        "Your primary role is to act as an expert computer science professor and career counselor. "
        "You help students by looking directly at their shared screens to debug code, explain complex graphs or research papers, and guide them through international scholarship and university application portals. "
        "You are fully bilingual. When a user connects, politely ask in English: 'Hello! I am EduMentor. Would you like to converse in English or Urdu?' "
        "Once they choose, switch completely to their preferred language. "
        "Always keep your answers highly concise, conversational, and directly related to what you see on their screen. Never give generic advice if you can reference the visual context."
    )
)

runner = Runner(
    app_name=APP_NAME,
    agent=agent,
    session_service=session_service
)

@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("✅ Frontend Connected!")

    user_id = "student_Ahsaan"
    session_id = "session_1"

    # Use bidirectional live streaming with manual activity signaling for push-to-talk.
    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        session_resumption=types.SessionResumptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
        )
    )

    session = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if not session:
        await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )

    live_request_queue = LiveRequestQueue()

    # Upstream path: route browser media/events into the Gemini Live request queue.
    async def upstream_task():
        try:
            while True:
                data = await websocket.receive_text()
                payload = json.loads(data)

                if payload["type"] == "image":
                    raw = payload["data"]
                    image_data = base64.b64decode(
                        raw.split(',')[1] if ',' in raw else raw
                    )
                    live_request_queue.send_realtime(
                        types.Blob(mime_type="image/jpeg", data=image_data)
                    )

                elif payload["type"] == "audio":
                    audio_data = base64.b64decode(payload["data"])
                    print(f"🎤 Audio chunk received: {len(audio_data)} bytes")
                    live_request_queue.send_realtime(
                        types.Blob(mime_type="audio/pcm;rate=16000", data=audio_data)
                    )

                elif payload["type"] == "activity_start":
                    # Explicitly mark user speech start for manual VAD turn control.
                    print("🟢 SIGNAL: Mic Opened")
                    live_request_queue.send_activity_start()

                elif payload["type"] == "activity_end":
                    # Explicitly mark user speech end to trigger model response generation.
                    print("🔴 SIGNAL: Mic Closed -> Triggering Response")
                    live_request_queue.send_activity_end()

                elif payload["type"] == "text":
                    print("💬 TEXT:", payload["data"])
                    live_request_queue.send_content(
                        types.Content(parts=[types.Part(text=payload["data"])])
                    )

        except WebSocketDisconnect:
            print("🔌 Client disconnected (upstream)")
        except Exception as e:
            print(f"🔥 UPSTREAM ERROR: {e}")
        finally:
            live_request_queue.close()

    # Downstream path: stream model events back to the browser over the same WebSocket.
    async def downstream_task():
        try:
            print("🚀 Downstream: Connecting to Gemini Live...")
            async for event in runner.run_live(
                user_id=user_id,
                session_id=session_id,
                live_request_queue=live_request_queue,
                run_config=run_config
            ):
                event_dict = json.loads(event.model_dump_json(exclude_none=True, by_alias=True))

                if event_dict.get("content"):
                    print(f"📦 Content parts: {list(event_dict['content'].get('parts', [{}])[0].keys())}")
                    parts = event_dict['content'].get('parts', [])
                    for p in parts:
                        if 'inlineData' in p:
                            print(f"🔊 AUDIO STRUCTURE: {list(p['inlineData'].keys())}")
                            print(f"🔊 MIME TYPE: {p['inlineData'].get('mimeType', 'NO MIME TYPE')}")
                            break

                if event_dict.get("turnComplete"):
                    print("✅ Turn Complete!")

                if event_dict.get("outputTranscription"):
                    print(f"🗣️ AI said: {event_dict['outputTranscription']}")

                event_json = event.model_dump_json(exclude_none=True, by_alias=True)
                await websocket.send_text(event_json)

        except Exception as e:
            print(f"🔥 DOWNSTREAM ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    try:
        await asyncio.gather(upstream_task(), downstream_task())
    finally:
        print("❌ Session Closed.")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)