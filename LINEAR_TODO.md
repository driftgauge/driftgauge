# Driftgauge Linear Backlog

Ready to copy into Linear once access is available.

## 1. Source management UX
- Add per-source edit, enable or disable, retry-now, and delete controls
- Show clearer source status chips and last-run timestamps
- Prevent accidental destructive actions with lightweight confirmation

## 2. Ingestion quality filters
- Filter login walls, auth gates, dead-end recovery pages, and low-value boilerplate before import
- Add source-specific heuristics for Facebook, Instagram, X, Threads, TikTok, and Snapchat
- Surface why a source was skipped instead of silently importing junk or returning 0 items

## 3. Data cleanup tools
- Add admin cleanup actions to purge junk rows from earlier scraping passes
- Support deleting entries by source and time range
- Support clearing remembered ingested-item hashes for a source before reruns

## 4. Historical import adapters
- Support account exports and API-based imports for deeper retro history
- Separate export imports from anonymous scraping in the UI and docs
- Preserve source metadata so imported history is traceable and reversible

## 5. Auth polish
- Add password change flow
- Add clearer expired-session handling and re-login prompts
- Keep the login form hidden when a valid session already exists

## 6. Source health dashboard
- Summarize healthy, paused, failing, and empty sources
- Highlight repeated 404 or 429 failures
- Recommend likely fixes for broken handles or private profiles
