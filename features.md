I figured out why the contract data does not look right.   I don't think we are using the aggregate api endpoint (https://api.balldontlie.io/v1/contracts/players/aggregate). As I know of one player that resigned in october 2025 but we aren't showing that data here.   I want to include as much as possible here.   Include an indicator of when the players most recent contract expires in the roster listing too.

When you pull the injury data, is there any indicator on when it was last updated?  If not, can we attempt to do our own tracking of it and display when we think the data was last changed?   Not pulled from the API i mean, but actual content was changed.  Show that date time in mountain time on the page.

Is there more injury data we can add?  Like what types of injury they have?  Anything else in the api?

Let's explore the odds data we can get from BallDontLie.  Is it better than what we are doing now?  Does it go further out in the future?   Can we display more than just source like we are doing now?


Can we sort the listing of the injury report by the Return Date?

When I asked about replacing the odds collection with Ball Dont Lie, I think you might have been wrong.  I found via this endpoint you can get future data: https://api.balldontlie.io/v2/odds?dates[]=2026-01-04


Can we make a way to display special information in the game details (when you click on a game on the caledar) that comes from a static json text file on disk?  Create a structure for me with an example for Jan 9 being "Bruce Brown Bobble Head Night".



Are you able to scrape data from this webpage and add to that json? https://www.nba.com/nuggets/promotional-schedule. Can you make a standalone script to do it.  We'll only run it once.  It's more for future reference.


In the Nuggets Roster listing does "Under contract thru 2025 · RFA 2026" mean they are a free agent right now (It's Jan 2026)?  Should we have an indicator for that as well if so?  Something indicating the regular contract expired and they are a free agent would be great.

Is there an API or a schedule for which jersey the Nuggets are going to be wearing at upcoming games?  THere IS! https://lockervision.nba.com/team/denver-nuggets


Let's do a massive re-organization. On the main page let's replacce the header "Nikola Jokić Denver Nuggets | #15 | Center" With something more general like "NBA Stats . Fun".  

Let's move all the Nikola Jokic stats to his own dedicated page (menu at the top).  Include the "All-Time Records Watch" section, and the "Season Rankings (League-Wide)" section and the "Triple-Double Record Watch" section. 
Change "more stats" link to "Nuggets Stats".

Keep "2025-26 Conference Standings", "Injury Report", and  "Upcoming Games" on the main page"


-------









Can we error check something (this might be an indicator of a wider problem).   I see in "Season Rankings (League-Wide)" that joker is ranked 2 for points, but when you click on it and see the list of the leaders he is actually 3.   If you look at THESE stats, he dropped to 5.   That is points per game though.   Should we be tracking both and be more clear about points per game (PPG) and "Total Points"?   

Do I need to schedule a new cron job for the jeresey data or did it scrape all of them?



Jokic's stats under "Per-Game Rankings (2025-26 Season)" look a little weird now. FG%	3P%	FT% are all blank.    We get a lot of data from balldontlie.  If we need a new source we could use that?

Maybe this is the problem:
[5/6] Fetching league leaders...
  Fetching PTS... OK
  Fetching REB... OK
  Fetching AST... OK
  Fetching STL... OK
  Fetching BLK... OK
  Fetching FG_PCT... Error: Expecting value: line 1 column 1 (char 0)
  Fetching FG3_PCT... Error: Expecting value: line 1 column 1 (char 0)
  Fetching FT_PCT... Error: Expecting value: line 1 column 1 (char 0)
  Fetching EFF... OK
  Fetching FGM... OK
  Fetching FGA... OK
  Fetching FTM... OK
  Fetching FTA... OK
  Fetching OREB... OK
  Fetching DREB... OK
  Fetching MIN... OK
  Saved league_leaders.json


Regarding odds data, can we note in small print if the data came from the odds api or ball dont lie?

When you click on a future game in the calendar can we make the data a little more rich by including any injury information if available, and any odds if available.

I found this G-League API. Is there a way we might be able to pull the contract information from the missing players from it?  https://developer.sportradar.com/basketball/reference/g-league-overview


Can we go back in history and keep a historical record (including adding to it as time passes) and indicate in past games on the calendar if the nuggets beat the odds?

The recent games list on the "Denver Nuggets Stats" page is out of date. Is that not being updated any more?  Can you start the local instance so we can test it out locally first.    If you use the chrome plugin you can see what I mean here: https://www.nbastats.fun/

Can you make it more clear that those numbers are the Money LIne (if that is what they are?) Right now it just says the team names. 

Also I see the long list of odds with ALL the book makers now.  Can we show an average line if there are more than 1?


The main page header is a bit too wide (or I guess tall?).  On mobile it really takes up a lot of space.  Can we make it thinner?

OK that header looks better.  Can we make it more consistent across all the pages.  I think the Jokic page is still too wide/tall

The odds look weird in the "Upcoming Games" section. For the "Brooklyn Nets" game today, the bookmakers are in different boxes, without a clear indicator of who is favored.  But the "Philadelphia 76ers" are in the table format which is much more clear.   I want it to be consisent. And some sort of very clear highlight for who is favored.


Can we clean up the refresh_*.py scripts?  I think some are redundant now.  Can we get rid of whichever ones aren't needed?


--

On a few of the pop up details from clicking on a game on the calendar is getting way too tall (usually when there is a lot of injuried players) because there is no way to scroll.   Maybe we should make it wider?


Would it be possible to use the BallDontLie betting odds to report to build a live game perdiction when games are happening?  Maybe make a graph out of it?   Since they have so many bookmakers this should give a good overall prediction right?  Is there any other way to do a live game prediction?    Let's make a new "Live" page.  There is a Nuggets game starting soon that we can use as a test.


Is there a way to keep the contract data refresh in the scripts but make it refresh at a slower rate, like weekly?



Is it possible to add the current game clock to the live page?  No guessing.  Get this accurately from somewhere.


Let's work on the graph on the live page.   Can we have vertical lines marking each quarter?    Also, i noticed if you refresh the page you lose the history.  We want that to persist for the whole game.


Can we make the dots on the graph smaller.   Can we fill in the graph on the probability graph between the line and EVEN line?   Yellow on the top (for nuggets), some other color for the opponent.  It would be great if we can dynamically find a color that matches the oponent.