# Installation Guide for AI Dependencies

This guide explains how to install the required Python packages for the AI providers used by the ElevenLabs Voice Connector.

## Option 1: Use Odoo's Native AI Framework (Recommended)

The easiest way is to use Odoo's built-in AI framework. Make sure you have the **AI module** installed in Odoo:

1. Go to **Apps** in Odoo
2. Search for "AI" 
3. Install the **AI** module
4. Configure your AI provider in **Settings → AI**

This way, you don't need to install any additional Python packages!

## Option 2: Install Python Packages Directly

If you prefer to use direct API calls (or Odoo's AI module is not available), you need to install the Python packages on your Odoo server.

### For Odoo Cloud / Odoo.sh

If you're using Odoo Cloud or Odoo.sh, you'll need to add these to your requirements file or contact support.

### For Self-Hosted Odoo

1. **SSH into your Odoo server**
2. **Activate your Odoo virtual environment** (if you're using one)
3. **Install the packages:**

```bash
# For OpenAI
pip install openai

# For Google Gemini
pip install google-generativeai

# Or install both at once
pip install openai google-generativeai
```

4. **Restart your Odoo server** after installation

### Example Installation Commands

```bash
# If using a virtual environment
source /path/to/venv/bin/activate  # On Linux/Mac
# or
/path/to/venv/Scripts/activate  # On Windows

# Install packages
pip install openai google-generativeai

# Restart Odoo
sudo systemctl restart odoo  # Adjust based on your setup
```

## Configuration

After installation, configure your AI provider in Odoo:

1. Go to **Settings → Integrations → ElevenLabs Voice Connector**
2. Select your **AI Provider** (OpenAI, Google Gemini, or Odoo Native AI)
3. Enter your **AI Model** name (e.g., `gpt-3.5-turbo` for OpenAI, `gemini-pro` for Gemini)
4. Make sure your API keys are configured in the appropriate settings

## Troubleshooting

- **"Library not installed" error**: Make sure you installed the package in the same Python environment where Odoo is running
- **"API key not configured"**: Set your API keys in Odoo Settings
- **Still not working**: Check Odoo server logs for detailed error messages

## Recommended: Use Odoo Native AI

We strongly recommend using **Odoo's Native AI framework** (Option 1) as it:
- Doesn't require additional Python packages
- Is better integrated with Odoo
- Handles API keys and configuration automatically
- Works seamlessly with Odoo's AI features

