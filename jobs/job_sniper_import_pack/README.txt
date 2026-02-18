1) Google Sheets: import CSVs as NEW sheets named:
   settings, keywords_packs, jobs, messages, applications, events
2) Fill keywords_packs.query with your 6 validated queries
3) n8n server: copy .env.example -> .env, fill secrets, restart n8n
4) n8n UI: import the 3 workflow JSON files, set Google OAuth2 + Telegram credentials, activate WF1 then WF2 then WF3
