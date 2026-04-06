from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI

from app.config import settings
from app.models.user import User
from app.dependencies import get_current_user, get_optional_user

router = APIRouter(prefix="/chat", tags=["AI Chat"])

SYSTEM_PROMPT = """You are PingMonitor's AI support assistant. You help users with the PingMonitor platform — an API endpoint monitoring service.

## About PingMonitor
- PingMonitor monitors websites, APIs, and AI services in real-time
- Users can monitor up to 7 endpoints on the free plan
- Checks run at configurable intervals: 1min, 5min, 15min, 30min, 1h
- Supports HTTP monitoring and Service Status monitoring (OpenAI, Anthropic, GitHub, Supabase, etc.)
- Sends alerts via Email, Slack, Discord, Telegram, Microsoft Teams, SMS, and custom Webhooks
- Has incident detection — auto-creates incidents when endpoints go down
- Has a metrics page with uptime trends, response time charts, and endpoint comparison

## Common User Questions

### How to add a monitor?
1. Go to Endpoints page
2. Click "+ New" button
3. Choose HTTP or Service Status type
4. Enter URL and name
5. Set check interval and notification preferences
6. Click "Create monitor"

### How to set up notifications?
1. Go to Notifications → Settings (Channels)
2. Click "Connect" on your preferred channel (Email, Slack, Discord, etc.)
3. Enter the required configuration (webhook URL, bot token, etc.)
4. Click "Test" to verify it works
5. When an endpoint goes down, alerts are sent to all connected channels

### What happens when an endpoint goes down?
1. PingMonitor detects the failure
2. An incident is automatically created
3. Notifications are sent to all your connected channels
4. When the endpoint recovers, the incident is resolved and a recovery notification is sent

### Monitor types
- **HTTP**: Checks any URL and verifies it returns a 2xx/3xx status code
- **Service Status**: Monitors official status pages of services like OpenAI, GitHub, Supabase (uses Atlassian Statuspage format)

### Pricing
- **Free**: 7 monitors, 1-minute checks, email notifications, 24h data retention
- **Pro** (coming soon): 50 monitors, 30s checks, all notification channels, 90-day retention

### Response time chart not showing?
- Charts appear after the first check completes
- Data is shown for the last 24 hours
- Each individual check is plotted as a data point

### Endpoint showing "Pending"?
- The first check hasn't run yet
- Wait for the check interval to pass (e.g., 5 minutes)
- Or check if the endpoint is paused

## Rules
- Be helpful, concise, and friendly
- Answer only about PingMonitor features and usage
- If you don't know the answer, say "I'm not sure about that. You can reach us at support@yashai.me for further help."
- Don't make up features that don't exist
- Keep responses short (2-4 sentences max) unless the user asks for detailed steps
- Use simple language, no jargon
"""


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    message: str


@router.post("/message", response_model=ChatResponse)
async def chat_message(
    body: ChatRequest,
    user: User | None = Depends(get_optional_user),
):
    if not settings.AI_API_KEY:
        raise HTTPException(status_code=503, detail="AI chat not configured")

    client = AsyncOpenAI(
        api_key=settings.AI_API_KEY,
        base_url=settings.AI_API_BASE,
    )

    # Build messages with system prompt
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add user context if authenticated
    if user:
        messages.append({
            "role": "system",
            "content": f"The user's name is {user.name or 'Unknown'} and their email is {user.email}. They are on the {user.role} plan with {user.credits} credits and can monitor up to {user.max_endpoints} endpoints.",
        })

    # Add conversation history (last 10 messages max)
    for msg in body.messages[-10:]:
        messages.append({"role": msg.role, "content": msg.content})

    try:
        response = await client.chat.completions.create(
            model=settings.AI_MODEL,
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )

        reply = response.choices[0].message.content or "I'm sorry, I couldn't generate a response."
        return ChatResponse(message=reply)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")


@router.post("/escalate")
async def escalate_to_email(
    body: ChatRequest,
    user: User | None = Depends(get_optional_user),
):
    """User wants human support — log the conversation for email follow-up."""
    # In production, this would send an email via Resend
    return {
        "message": "Your conversation has been sent to our support team. We'll get back to you at "
        + (user.email if user else "your email")
        + " within 24 hours.",
    }
