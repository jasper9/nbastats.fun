I figured out why the contract data does not look right.   I don't think we are using the aggregate api endpoint (https://api.balldontlie.io/v1/contracts/players/aggregate). As I know of one player that resigned in october 2025 but we aren't showing that data here.   I want to include as much as possible here.   Include an indicator of when the players most recent contract expires in the roster listing too.

When you pull the injury data, is there any indicator on when it was last updated?  If not, can we attempt to do our own tracking of it and display when we think the data was last changed?   Not pulled from the API i mean, but actual content was changed.  Show that date time in mountain time on the page.

Is there more injury data we can add?  Like what types of injury they have?  Anything else in the api?

Let's explore the odds data we can get from BallDontLie.  Is it better than what we are doing now?  Does it go further out in the future?   Can we display more than just source like we are doing now?


Can we sort the listing of the injury report by the Return Date?

When I asked about replacing the odds collection with Ball Dont Lie, I think you might have been wrong.  I found via this endpoint you can get future data: https://api.balldontlie.io/v2/odds?dates[]=2026-01-04

-------

Let's do a massive re-organization. On the main page let's replacce the header "Nikola Jokić Denver Nuggets | #15 | Center" With something more general like "NBA Stats . Fun".  

Let's move all the Nikola Jokic stats to his own dedicated page (menu at the top).  Include the "All-Time Records Watch" section, and the "Season Rankings (League-Wide)" section and the "Triple-Double Record Watch" section. 
Change "more stats" link to "Nuggets Stats".

Keep "2025-26 Conference Standings", "Injury Report", and  "Upcoming Games" on the main page"


In the Nuggets Roster listing does "Under contract thru 2025 · RFA 2026" mean they are a free agent right now (It's Jan 2026)?  Should we have an indicator for that as well if so?  Something indicating the regular contract expired and they are a free agent would be great.

Can we error check something (this might be an indicator of a wider problem).   I see in "Season Rankings (League-Wide)" that joker is ranked 2 for points, but when you click on it and see the list of the leaders he is actually 3.   If you look at THESE stats, he dropped to 5.   That is points per game though.   Should we be tracking both and be more clear about points per game (PPG) and "Total Points"?   


--





Can you merge the refresh_balldontlie.py process into refresh_cache.py so we just have to run one?


When you click on a future game in the calendar can we make the data a little more rich by including any injury information if available, and any odds if available.


Can we go back in history and keep a historical record (including adding to it as time passes) and indicate in past games on the calendar if the nuggets beat the odds?






Coming back to the 2 way player thing. I see at least one player isn't listed, it might be because they are a 2way player with the G-leage.  I want to see all that data too. I found this API that might have it? https://developer.sportradar.com/basketball/reference/g-league-overview.   See if they have NBA data as well that might have some of what we are missing.   A good example you can look for is the Denver Nuggets player Spencer Jones.   He is on the roster in the data we have, but not listed in the contracts.  


Would it be possible to use the BallDontLie betting odds to report to build a live game perdiction when games are happening?  Maybe make a graph out of it?   Since they have so many bookmakers this should give a good overall prediction right?