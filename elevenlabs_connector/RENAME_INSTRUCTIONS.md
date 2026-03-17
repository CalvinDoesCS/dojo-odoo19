# URGENT: Directory Rename Required

## Problem
Odoo cannot load modules with spaces in the directory name. The error you're seeing is:
```
FileNotFoundError: Invalid module name: Eleven Labs Odoo connector
```

## Solution
You **MUST** rename the directory before Odoo can recognize this module.

### Option 1: Rename via File Explorer (Recommended)
1. Close Odoo server if running
2. Navigate to: `C:\Users\MSS\Desktop\Dow Group apps\`
3. Rename folder from: `Eleven Labs Odoo connector`
4. To: `elevenlabs_connector`
5. Restart Odoo server
6. Update Apps List

### Option 2: Rename via Command Line
```powershell
cd "C:\Users\MSS\Desktop\Dow Group apps"
Rename-Item "Eleven Labs Odoo connector" "elevenlabs_connector"
```

### Option 3: Use Git (if using version control)
```bash
git mv "Eleven Labs Odoo connector" "elevenlabs_connector"
```

## After Renaming
1. The module will be recognized as `elevenlabs_connector`
2. Update Apps List in Odoo
3. Install the module
4. Configure in Settings → Integrations → ElevenLabs

## Why This Happens
Odoo module names must be:
- Valid Python identifiers
- No spaces
- Start with letter or underscore
- Contain only letters, numbers, and underscores

The directory name becomes the technical module name used for imports and module identification.

