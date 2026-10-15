"""
🛡️ GROUP MANAGEMENT ENGINE (Multi-Bot ka doosra personality)
==========================================================

Is folder me wo saare features hain jo "Group Manager Bot" ko banate hain:

• ``core.py``      — shared helpers (mode gate, warn/ban/mute, admin utils)
• ``blacklist.py`` — word / link / media blocking
• ``language.py``  — language filter (Unicode-script detection)
• ``moderation.py``— warn, ban, mute, kick, purge, lock, slowmode
• ``reports.py``   — admin-tag report system
• ``antiflood.py`` — per-user message-rate guard (auto mute + warn)
• ``menu.py``      — group control-panel + PM group-manager menu

Ye folder ``plugins/`` se alag hai — bot ke plugin loader me EXTRA root ke
t taur par register hota hai (bot.py → ``EXTRA_PLUGIN_ROOTS``), isliye
group-management ka code filter-bot ke code se physically alag rehta hai.

⚠️ IMPORTANT: Ye features SIRF un groups me chalti hain jinka group-mode
``MODE_MGMT`` hai. Auto-filter mode wale groups me ye sab dormant rehta hai
(aur wahan auto-filter chalta hai) — isi tarah user ne decide kiya tha.
"""

__all__ = ["core", "blacklist", "language", "moderation", "reports", "antiflood", "menu"]
