#!/usr/bin/env python3
"""
Post-game video fetcher for Nuggets games.

Fetches interview and press conference videos from:
- YouTube (DNVR Sports channel) via YouTube Data API
- Provides links to Twitter/X accounts for manual browsing

Requires YOUTUBE_API_KEY in .env file.
Get a free API key at: https://console.cloud.google.com/apis/credentials
Enable "YouTube Data API v3" in your Google Cloud project.
"""

import os
import re
import requests
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv()

# YouTube Data API configuration
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
YOUTUBE_API_BASE = 'https://www.googleapis.com/youtube/v3'

# YouTube channels to search for Nuggets content
YOUTUBE_CHANNELS = {
    'DNVR_Sports': {
        'channel_id': 'UCbT-a4MHWQZCX_wSZPLzWdg',  # DNVR Sports channel ID
        'name': 'DNVR Sports',
        'priority': 1,
    },
    'Denver_Nuggets': {
        'channel_id': 'UCVOEaItME1FzGqUjVIoFzPA',  # Official Nuggets channel
        'name': 'Denver Nuggets',
        'priority': 2,
    },
}

# Twitter/X accounts to link for post-game content
TWITTER_ACCOUNTS = [
    {
        'handle': 'nuggets',
        'name': 'Denver Nuggets',
        'url': 'https://x.com/nuggets',
        'description': 'Official team account',
    },
    {
        'handle': 'DNVR_Nuggets',
        'name': 'DNVR Nuggets',
        'url': 'https://x.com/DNVR_Nuggets',
        'description': 'DNVR Nuggets coverage',
    },
    {
        'handle': 'LegionHoops',
        'name': 'Legion Hoops',
        'url': 'https://x.com/LegionHoops',
        'description': 'NBA news and highlights',
    },
    {
        'handle': 'SleeperNuggets',
        'name': 'Sleeper Nuggets',
        'url': 'https://x.com/SleeperNuggets',
        'description': 'Nuggets news and analysis',
    },
    {
        'handle': 'Tatianaclinares',
        'name': 'Tatiana Clinarés',
        'url': 'https://x.com/Tatianaclinares',
        'description': 'Nuggets reporter',
    },
    {
        'handle': 'nuggetsfan4ever',
        'name': 'Nuggets Fan Forever',
        'url': 'https://x.com/nuggetsfan4ever',
        'description': 'Fan account with clips',
    },
]

# Keywords for finding post-game content
POSTGAME_KEYWORDS = [
    'postgame',
    'post-game',
    'post game',
    'press conference',
    'interview',
    'locker room',
    'reaction',
    'breakdown',
]

# Player names to search for (key players)
NUGGETS_PLAYERS = [
    'Jokic',
    'Murray',
    'Porter',
    'Gordon',
    'Braun',
    'Russell',
    'Watson',
    'Malone',  # Coach
]

MOUNTAIN_TZ = ZoneInfo('America/Denver')


def get_youtube_api_key():
    """Get YouTube API key from environment."""
    return os.getenv('YOUTUBE_API_KEY')


def search_youtube_channel(channel_id: str, query: str, published_after: datetime,
                           max_results: int = 10) -> list:
    """
    Search a YouTube channel for videos matching a query.

    Args:
        channel_id: YouTube channel ID
        query: Search query string
        published_after: Only return videos published after this time
        max_results: Maximum number of results to return

    Returns:
        List of video objects with id, title, description, published_at, thumbnail
    """
    api_key = get_youtube_api_key()
    if not api_key:
        return []

    try:
        # Format datetime for YouTube API (RFC 3339)
        published_after_str = published_after.strftime('%Y-%m-%dT%H:%M:%SZ')

        params = {
            'key': api_key,
            'channelId': channel_id,
            'q': query,
            'type': 'video',
            'order': 'date',
            'publishedAfter': published_after_str,
            'maxResults': max_results,
            'part': 'snippet',
        }

        resp = requests.get(f'{YOUTUBE_API_BASE}/search', params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        videos = []
        for item in data.get('items', []):
            snippet = item.get('snippet', {})
            video_id = item.get('id', {}).get('videoId')

            if video_id:
                videos.append({
                    'id': video_id,
                    'url': f'https://www.youtube.com/watch?v={video_id}',
                    'title': snippet.get('title', ''),
                    'description': snippet.get('description', ''),
                    'published_at': snippet.get('publishedAt', ''),
                    'thumbnail': snippet.get('thumbnails', {}).get('medium', {}).get('url', ''),
                    'channel': snippet.get('channelTitle', ''),
                })

        return videos

    except Exception as e:
        print(f"Error searching YouTube: {e}")
        return []


def fetch_postgame_videos(opponent: str, game_date: datetime,
                          hours_after: int = 24) -> dict:
    """
    Fetch post-game videos for a Nuggets game.

    Args:
        opponent: Opponent team name (e.g., "Lakers", "MEM")
        game_date: Date/time of the game
        hours_after: How many hours after game to search for videos

    Returns:
        Dict with 'youtube_videos' list and 'twitter_links' list
    """
    result = {
        'youtube_videos': [],
        'twitter_links': TWITTER_ACCOUNTS.copy(),
        'fetched_at': datetime.now(MOUNTAIN_TZ).isoformat(),
    }

    api_key = get_youtube_api_key()
    if not api_key:
        print("YouTube API key not configured - skipping video fetch")
        return result

    # Build search queries
    # Try multiple queries to find relevant content
    queries = [
        f'Nuggets {opponent} postgame',
        f'Nuggets {opponent} interview',
        f'Nuggets {opponent} press conference',
        f'Jokic {opponent}',
        f'Nuggets {opponent}',
    ]

    # Search window: from game time to hours_after later
    search_start = game_date

    seen_video_ids = set()
    all_videos = []

    for channel_name, channel_info in YOUTUBE_CHANNELS.items():
        for query in queries:
            videos = search_youtube_channel(
                channel_info['channel_id'],
                query,
                search_start,
                max_results=5
            )

            for video in videos:
                # Deduplicate
                if video['id'] not in seen_video_ids:
                    seen_video_ids.add(video['id'])
                    video['source'] = channel_info['name']
                    video['priority'] = channel_info['priority']
                    all_videos.append(video)

    # Sort by priority (lower is better) then by date (newest first)
    all_videos.sort(key=lambda v: (v['priority'], v['published_at']), reverse=False)

    # Filter to only include relevant videos
    relevant_videos = []
    for video in all_videos:
        title_lower = video['title'].lower()
        desc_lower = video['description'].lower()

        # Check if it's likely a post-game video
        is_postgame = any(kw in title_lower or kw in desc_lower
                         for kw in POSTGAME_KEYWORDS)
        has_nuggets = 'nuggets' in title_lower or 'nuggets' in desc_lower
        has_opponent = opponent.lower() in title_lower or opponent.lower() in desc_lower
        has_player = any(player.lower() in title_lower
                        for player in NUGGETS_PLAYERS)

        # Include if it seems relevant
        if is_postgame or (has_nuggets and (has_opponent or has_player)):
            relevant_videos.append(video)

    result['youtube_videos'] = relevant_videos[:10]  # Limit to top 10

    return result


def fetch_videos_for_game_history(game_id: str, opponent: str,
                                   game_datetime: datetime) -> dict:
    """
    Fetch videos for a completed game and format for storage in game history.

    Args:
        game_id: The game ID for the history file
        opponent: Opponent team name
        game_datetime: When the game was played

    Returns:
        Dict ready to be added to game history JSON
    """
    videos_data = fetch_postgame_videos(opponent, game_datetime)

    return {
        'postgame_media': {
            'youtube_videos': videos_data['youtube_videos'],
            'twitter_links': videos_data['twitter_links'],
            'fetched_at': videos_data['fetched_at'],
            'opponent': opponent,
            'game_date': game_datetime.strftime('%Y-%m-%d'),
        }
    }


# For testing
if __name__ == '__main__':
    print("Testing post-game video fetcher...")
    print(f"YouTube API Key configured: {bool(get_youtube_api_key())}")

    if get_youtube_api_key():
        # Test search
        test_date = datetime.now(MOUNTAIN_TZ) - timedelta(days=1)
        print(f"\nSearching for videos since {test_date}...")

        result = fetch_postgame_videos('Grizzlies', test_date)

        print(f"\nFound {len(result['youtube_videos'])} YouTube videos:")
        for v in result['youtube_videos'][:5]:
            print(f"  - {v['title'][:60]}...")
            print(f"    {v['url']}")

        print(f"\nTwitter links ({len(result['twitter_links'])}):")
        for t in result['twitter_links']:
            print(f"  - @{t['handle']}: {t['url']}")
    else:
        print("\nTo enable YouTube search, add YOUTUBE_API_KEY to your .env file")
        print("Get a free key at: https://console.cloud.google.com/apis/credentials")
        print("Enable 'YouTube Data API v3' in your Google Cloud project")
