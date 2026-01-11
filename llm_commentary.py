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
}


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
        event_type: One of 'lead_change', 'largest_lead', 'dunk', 'tie_game', 'quarter_end'
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

        # Call Claude Haiku - fast and cheap
        # Using temperature=1.0 for maximum creativity and variety
        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=50,  # Keep responses short
            temperature=1.0,  # Max temperature for variety
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
