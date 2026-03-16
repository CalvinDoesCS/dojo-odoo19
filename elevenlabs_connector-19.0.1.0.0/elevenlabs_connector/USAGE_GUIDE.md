# ElevenLabs Voice Connector - Usage Guide

## 🎤 How to Use the Voice Assistant

### Accessing the Voice Assistant

1. **Via Menu**: Go to **Settings → Voice Assistant** (in the Administration menu)
2. **Direct URL**: Navigate to `/elevenlabs/voice` in your browser
3. **Conversation History**: Go to **Settings → Voice Conversations** to view past interactions

### Using the Voice Assistant

#### Method 1: Record Voice (Recommended)

1. **Click the microphone button** on the Voice Assistant page
2. **Speak your question** clearly (e.g., "Show me my appointments for tomorrow")
3. **Click the button again** to stop recording
4. The system will:
   - Transcribe your voice to text
   - Process your question using AI
   - Query your Odoo database (if needed)
   - Generate a spoken response
   - Play the audio response automatically

#### Method 2: Upload Audio File

1. Click **"Upload Audio File"** button
2. Select an audio file (MP3, WAV, etc.) from your computer
3. The system will process it the same way as recorded voice

### Example Questions You Can Ask

**About Appointments:**
- "Show me my appointments for tomorrow"
- "What meetings do I have this week?"
- "List all calendar events for next Monday"

**About Invoices:**
- "Show me unpaid invoices"
- "What are the open invoices for customer Smith?"
- "How many invoices were created this month?"

**About CRM Leads:**
- "List my top 5 leads by expected revenue"
- "Show me all open opportunities"
- "What leads are assigned to me?"

**About Employees:**
- "Who is employee John Doe?"
- "Show me all employees in the Sales department"

**About Partners/Customers:**
- "Find customer ABC Corporation"
- "Show me all partners in New York"

### How It Works

1. **Speech-to-Text**: Your voice is transcribed using ElevenLabs STT
2. **AI Processing**: The transcribed text is sent to your configured AI provider (OpenAI/Gemini)
3. **Database Query**: If your question requires data, the AI generates a query
4. **Results**: The system retrieves data from your Odoo database
5. **Text-to-Speech**: The response is converted to speech using ElevenLabs TTS
6. **Audio Playback**: You hear the spoken response

### Viewing Conversation History

- Go to **Settings → Voice Conversations**
- View all your past voice interactions
- See transcribed text, AI responses, and database queries
- Listen to audio recordings of your questions and responses

### Troubleshooting

**No audio playback?**
- Check your browser's audio permissions
- Ensure your speakers/headphones are working
- Try refreshing the page

**Connection test fails?**
- Verify your ElevenLabs API key is correct
- Check your internet connection
- Make sure you have API credits in your ElevenLabs account

**AI not responding?**
- Check your AI provider settings (OpenAI/Gemini API key)
- Verify the AI model name is correct
- Check the logs in Settings → Voice Conversations for errors

**Database queries not working?**
- Ensure the models you're querying are in the "Queryable Models" list
- Check that you have read permissions for those models
- Verify your question is clear and specific

### Tips for Best Results

1. **Speak clearly** and at a moderate pace
2. **Be specific** in your questions (include dates, names, etc.)
3. **Use natural language** - the AI understands conversational queries
4. **Check conversation history** to see what was understood
5. **Configure queryable models** in settings to limit what can be accessed

### Next Steps

- Configure your AI provider (OpenAI or Gemini) in Settings → AI
- Set up queryable models to control database access
- Try different voice questions to explore the system
- Review conversation history to improve your queries

Enjoy using your voice-powered Odoo assistant! 🎉

