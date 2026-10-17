# Submission form text

**Challenge:** Manufacturing: Intelligent Operations & Industrial Efficiency
**Prototype link:** https://andon-agent-b9c77.web.app
**GitHub:** https://github.com/Likhith-BlueLotus/andon-agent
**Demo video:** https://youtu.be/lBHRCLir0A8 (3:29, public)
**Deck PDF:** upload AndonAgent_AIBuilderCup.pptx.pdf (team SUTRA final, 18 slides, 1.5 MB)

## Brief description (paste as-is)

Andon Agent investigates a stopped car-plant line like a reliability engineer. Five Gemini agents built with Google ADK plan checks, run change-point analytics on telemetry and machine audio, cite the manual and rank root causes; a deterministic verifier (code, no LLM) re-checks every claim and strikes out what it cannot back. A human accepts the cause, ticks verbatim lockout/tagout steps (translated to Hindi/Tamil/more) and approves a draft work order; nothing touches a machine. Measured: top-1 0.98 (60 synthetic) and 0.76 (17 real-signal scenarios); 1 unsupported claim in 586 vs 54 in 645 for one long prompt; ~$0.11 per diagnosis. Google: Gemini 3.8 Flash + 3.1 Flash-Lite on Vertex AI (context cache, structured output, audio, voice notes, CSV mapping); Cloud Run hosts the FastAPI SSE agent API; Firebase Hosting serves the React console and technician phone view; Firestore keeps the append-only audit log, mock CMMS work orders and budget limits; plus Cloud Storage (audio, manuals, data), Secret Manager.
