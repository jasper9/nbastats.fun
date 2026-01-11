"""
LLM-enhanced commentary for NBA live feed.
Uses Claude Haiku for cost-effective real-time commentary on exciting events.

Trigger Events:
- Lead changes
- Largest leads (5+ points)
- Dunks/highlight plays
- Tie games
- End of quarters
"""

import os
import random
from datetime import datetime
from collections import deque

# Try to import anthropic, gracefully degrade if not available
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# Track recent responses to help avoid repetition
_recent_responses = deque(maxlen=20)

# Commentary styles for different events
# Each prompt emphasizes variety and unique phrasing
COMMENTARY_PROMPTS = {
    'lead_change': """You are a creative NBA commentator. Generate ONE short sentence (max 15 words) about this lead change.

{leader} now leads {away_team} vs {home_team}, Q{period}

CRITICAL: Your response MUST be different from these recent calls:
{recent_calls}

Be inventive - use metaphors from sports, weather, warfare, or pop culture. No cliches like "takes the lead" or "in front". No emojis.""",

    'largest_lead': """You are an NBA stats analyst. Generate ONE insightful sentence (max 15 words) about a team building their largest lead.

Game: {away_team} vs {home_team}
Team with lead: {leader}
Lead amount: +{lead_amount}
Score: {away_team} {away_score} - {home_team} {home_score}
Quarter: Q{period}

IMPORTANT: Be creative! Don't just say "largest lead" - describe the momentum shift uniquely. Focus on game control or psychological edge. No hashtags or emojis.""",

    'dunk': """You are a legendary NBA announcer known for unique, memorable calls. Generate ONE explosive sentence (max 15 words) about this dunk.

Player: {player}
Team: {team}

CRITICAL: Your response MUST be completely different from these recent calls - DO NOT use similar words or structure:
{recent_calls}

Be wildly creative with fresh vocabulary. Draw from: mythology, natural disasters, sci-fi, action movies, martial arts, video games, or invent something entirely new. Surprise me! No emojis.""",

    'tie_game': """You are a drama-building NBA announcer. Generate ONE tense sentence (max 15 words) about a tie game.

Game: {away_team} vs {home_team}
Score: {score}-{score}
Quarter: Q{period}

IMPORTANT: Build unique suspense each time! Avoid "all tied up" or "back to even". Find fresh metaphors - chess match, boxing bout, thriller movie vibes. No hashtags or emojis.""",

    'quarter_end': """You are an NBA analyst. Generate ONE brief summary sentence (max 20 words) about the end of a quarter.

Game: {away_team} vs {home_team}
Score: {away_team} {away_score} - {home_team} {home_score}
Quarter completed: Q{period}
Leader: {leader} by {lead_diff}

IMPORTANT: Vary your analysis! Sometimes focus on offense, sometimes defense. Mention momentum, energy, crowd, or strategy shifts. Be analytical but fresh. No hashtags or emojis.""",

    'quarter_summary': """You are an expert NBA analyst providing a detailed quarter recap. Write a comprehensive 3-4 sentence summary of the quarter that just ended.

Game: {away_team} vs {home_team}
Quarter completed: Q{period}
Current Score: {away_team} {away_score} - {home_team} {home_score}
Leader: {leader} by {lead_diff}
Lead changes this game: {lead_changes}
Largest lead: {largest_lead_team} +{largest_lead}

Provide insightful analysis covering:
- Who controlled the quarter and how
- Key momentum shifts or runs
- What each team needs to do going forward
- The overall flow and pace of the game

Be analytical and engaging. Write like you're on ESPN. No hashtags or emojis.""",

    'game_summary': """You are an NBA analyst. Provide a brief final game recap in EXACTLY this bullet point format:

Game: {away_team} {away_score} - {home_team} {home_score}
Winner: {winner} by {margin}
Lead changes: {lead_changes}
Biggest lead: {largest_lead_team} +{largest_lead}

Respond with EXACTLY 3 bullet points (use • character), each 8-12 words max:
• [Key storyline or turning point]
• [Standout performance or deciding factor]
• [What this means going forward]

Example format:
• Jazz dominated early but couldn't sustain momentum
• Hornets' bench outscored starters in crucial third quarter
• Charlotte improves playoff positioning with this road win

Keep it punchy and insightful. No hashtags or emojis.""",
}

# Event types that require longer responses (quarter summaries need more tokens)
LONG_SUMMARY_EVENTS = {'quarter_summary'}
# Game summary uses bullet points so needs less tokens
MEDIUM_SUMMARY_EVENTS = {'game_summary'}


def get_client():
    """Get Anthropic client with API key from environment."""
    if not ANTHROPIC_AVAILABLE:
        return None
    api_key = os.getenv('ANTHROPIC_API_KEY')
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def generate_llm_commentary(event_type, context):
    """
    Generate LLM commentary for an exciting event.

    Args:
        event_type: One of 'lead_change', 'largest_lead', 'dunk', 'tie_game', 'quarter_end',
                   'quarter_summary', 'game_summary'
        context: Dict with event-specific context (teams, scores, players, etc.)

    Returns:
        str: Generated commentary or None if LLM unavailable/failed
    """
    global _recent_responses

    client = get_client()
    if not client:
        return None

    prompt_template = COMMENTARY_PROMPTS.get(event_type)
    if not prompt_template:
        return None

    try:
        # Add recent responses to context for prompts that use it
        if '{recent_calls}' in prompt_template:
            recent = list(_recent_responses)[-10:] if _recent_responses else []
            if recent:
                context['recent_calls'] = '\n'.join(f'- "{r}"' for r in recent)
            else:
                context['recent_calls'] = '(none yet - be original!)'

        # Format the prompt with context
        prompt = prompt_template.format(**context)

        # Use more tokens for longer summaries (quarter recaps)
        if event_type in LONG_SUMMARY_EVENTS:
            max_tokens = 250
            temperature = 0.8
        elif event_type in MEDIUM_SUMMARY_EVENTS:
            max_tokens = 120  # Bullet points need less
            temperature = 0.7
        else:
            max_tokens = 50
            temperature = 1.0

        # Call Claude Haiku - fast and cheap
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        # Extract text from response
        if response.content and len(response.content) > 0:
            result = response.content[0].text.strip()
            # Track this response to avoid repetition
            if result:
                _recent_responses.append(result)
            return result
        return None

    except Exception as e:
        print(f"LLM commentary error: {e}")
        return None


def enhance_message_with_llm(message, game_info):
    """
    Check if a message should be enhanced with LLM commentary.

    Args:
        message: Dict with message data (type, team, etc.)
        game_info: Dict with game context

    Returns:
        str or None: LLM-generated commentary to append, or None
    """
    msg_type = message.get('type')

    # Build context from message and game info
    context = {
        'home_team': game_info.get('home_team', 'HOME'),
        'away_team': game_info.get('away_team', 'AWAY'),
        'home_score': message.get('score', '0-0').split(' - ')[1].split()[0] if ' - ' in message.get('score', '') else '0',
        'away_score': message.get('score', '0-0').split()[1] if len(message.get('score', '').split()) > 1 else '0',
        'period': message.get('period', 1),
    }

    # Parse score properly: "CHI 45 - MIL 50" format
    score_str = message.get('score', '')
    if ' - ' in score_str:
        parts = score_str.split(' - ')
        if len(parts) == 2:
            away_part = parts[0].split()  # "CHI 45"
            home_part = parts[1].split()  # "MIL 50"
            if len(away_part) >= 2 and len(home_part) >= 2:
                context['away_score'] = away_part[-1]
                context['home_score'] = home_part[-1]

    # Lead change
    if message.get('is_lead_change'):
        context['leader'] = message.get('team', 'Team')
        return generate_llm_commentary('lead_change', context)

    # Largest lead
    if message.get('is_largest_lead'):
        context['leader'] = message.get('team', 'Team')
        context['lead_amount'] = message.get('lead_amount', 5)
        return generate_llm_commentary('largest_lead', context)

    # Dunk
    if msg_type == 'hype' and 'POSTER' in message.get('text', ''):
        context['player'] = message.get('text', '').split('POSTER!')[1].split('throws')[0].strip() if 'throws' in message.get('text', '') else 'Player'
        context['team'] = message.get('team', 'Team')
        context['description'] = message.get('text', '')
        return generate_llm_commentary('dunk', context)

    # Tie game
    if msg_type == 'tie':
        score_match = message.get('text', '')
        if '-' in score_match:
            score_val = score_match.split()[-1].split('-')[0]
            context['score'] = score_val
        else:
            context['score'] = context['home_score']
        return generate_llm_commentary('tie_game', context)

    # Quarter end (from StatsNerd summary)
    if msg_type == 'summary' and 'Quarter' in message.get('text', ''):
        # Extract leader info
        text = message.get('text', '')
        if 'leads by' in text:
            parts = text.split('leads by')
            context['leader'] = parts[0].replace('Quarter', '').strip().split()[-1]
            context['lead_diff'] = parts[1].strip().rstrip('.')
        else:
            context['leader'] = 'Tied'
            context['lead_diff'] = '0'
        return generate_llm_commentary('quarter_end', context)

    return None


# Cache for LLM responses to avoid duplicate calls
# Note: We intentionally DON'T cache 'dunk' events to ensure variety
_llm_cache = {}
MAX_CACHE_SIZE = 100

# Events that should always generate fresh responses (no caching)
UNCACHED_EVENTS = {'dunk'}


def get_cached_or_generate(event_key, event_type, context):
    """
    Get cached LLM response or generate new one.
    Prevents duplicate API calls for the same event.
    Note: Dunk events are never cached to ensure variety.
    """
    global _llm_cache

    # Don't cache certain event types to ensure variety
    if event_type in UNCACHED_EVENTS:
        return generate_llm_commentary(event_type, context)

    if event_key in _llm_cache:
        return _llm_cache[event_key]

    commentary = generate_llm_commentary(event_type, context)

    if commentary:
        # Manage cache size
        if len(_llm_cache) >= MAX_CACHE_SIZE:
            # Remove oldest entries
            oldest_keys = list(_llm_cache.keys())[:20]
            for key in oldest_keys:
                del _llm_cache[key]

        _llm_cache[event_key] = commentary

    return commentary


# =============================================================================
# PERSONA-BASED MESSAGE REFINEMENT
# =============================================================================

# Toggle for LLM refinement (set to False to use hardcoded messages)
ENABLE_LLM_REFINEMENT = True

# Bot personas with detailed character descriptions
BOT_PERSONAS = {
    'hype_man': """You are HypeMan, an INCREDIBLY enthusiastic NBA announcer who lives for the big moments.
Your style: Over-the-top excited, uses lots of energy words, occasionally ALL CAPS for emphasis.
You sound like a mix of Kevin Harlan and a WWE announcer. You make every play sound legendary.
Keep responses to ONE sentence, max 20 words. Use 2-3 emojis max. Never use hashtags.""",

    'play_by_play': """You are PlayByPlay, a professional NBA play-by-play announcer.
Your style: Clear, informative, occasionally witty. You call the action accurately with flair.
You sound like Mike Breen or Ian Eagle - professional but with personality.
Keep responses to ONE sentence, max 15 words. Use 1 emoji at the start. Never use hashtags.""",

    'stats_nerd': """You are StatsNerd, an analytical NBA commentator obsessed with numbers and context.
Your style: Data-driven, insightful, finds interesting statistical angles. You love advanced stats.
You sound like Zach Lowe or a sharp analytics writer.
Keep responses to ONE sentence, max 20 words. Use 📊 emoji at start. Never use hashtags.""",

    'historian': """You are Historian, an NBA historian who provides rich historical context.
Your style: Knowledgeable, reverent of the game's history, draws parallels to past legends.
You sound like Bob Costas or an ESPN 30-for-30 narrator.
Keep responses to ONE sentence, max 25 words. Use 📜 emoji at start. Never use hashtags.""",

    'trash_talker': """You are TrashTalker, a playful commentator who adds spicy commentary.
Your style: Witty, slightly provocative, loves dramatic reactions. You keep it fun, never mean.
You sound like Charles Barkley or Shaq on Inside the NBA.
Keep responses to ONE sentence, max 15 words. Use 1-2 emojis. Never use hashtags.""",
}

# Event types that should be refined with LLM (to control costs)
REFINABLE_EVENTS = {
    'technical',
    'technical_hype',
    'flagrant',
    'flagrant_hype',
    'ejection',
    'ejection_hype',
    'hype',  # Dunks and highlight plays
    'lead_change',
    'block',
    'steal',
}

# Cache for refined messages
_refinement_cache = {}
MAX_REFINEMENT_CACHE = 200


def refine_message_with_persona(bot_type, gist, context=None):
    """
    Refine a message using LLM with the bot's persona.

    Args:
        bot_type: One of 'hype_man', 'play_by_play', 'stats_nerd', 'historian', 'trash_talker'
        gist: The core message/idea to express (what happened)
        context: Optional dict with additional context (player, team, score, etc.)

    Returns:
        str: Refined message or original gist if LLM unavailable
    """
    global _refinement_cache

    if not ENABLE_LLM_REFINEMENT:
        return gist

    client = get_client()
    if not client:
        return gist

    persona = BOT_PERSONAS.get(bot_type)
    if not persona:
        return gist

    # Create cache key from bot type and gist
    cache_key = f"{bot_type}:{gist[:50]}"
    if cache_key in _refinement_cache:
        return _refinement_cache[cache_key]

    try:
        # Build the prompt
        context_str = ""
        if context:
            context_str = f"\nContext: {context}"

        prompt = f"""{persona}

Rewrite this message in your unique voice. Keep the same meaning but make it YOUR style:
"{gist}"{context_str}

Respond with ONLY the rewritten message, nothing else."""

        # Call Claude Haiku
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=60,
            temperature=0.9,  # High creativity for variety
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        if response.content and len(response.content) > 0:
            result = response.content[0].text.strip()
            # Remove quotes if the model wrapped the response
            if result.startswith('"') and result.endswith('"'):
                result = result[1:-1]

            # Cache the result
            if len(_refinement_cache) >= MAX_REFINEMENT_CACHE:
                # Remove oldest entries
                oldest = list(_refinement_cache.keys())[:40]
                for k in oldest:
                    del _refinement_cache[k]
            _refinement_cache[cache_key] = result

            return result

        return gist

    except Exception as e:
        print(f"LLM refinement error: {e}")
        return gist


def should_refine_message(msg_type):
    """Check if a message type should be refined with LLM."""
    return ENABLE_LLM_REFINEMENT and msg_type in REFINABLE_EVENTS
