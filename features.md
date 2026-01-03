I figured out why the contract data does not look right.   I don't think we are using the aggregate api endpoint (https://api.balldontlie.io/v1/contracts/players/aggregate). As I know of one player that resigned in october 2025 but we aren't showing that data here.   I want to include as much as possible here.   Include an indicator of when the players most recent contract expires in the roster listing too.

When you pull the injury data, is there any indicator on when it was last updated?  If not, can we attempt to do our own tracking of it and display when we think the data was last changed?   Not pulled from the API i mean, but actual content was changed.  Show that date time in mountain time on the page.

Is there more injury data we can add?  Like what types of injury they have?  Anything else in the api?
-------

Let's explore the odds data we can get from BallDontLie.  Is it better than what we are doing now?  Does it go further out in the future?   Can we display more than just source like we are doing now?




I see at least one player isn't listed, it might be because they are a 2way player with the G-leage.  I want to see all that data too. I found this API that might have it? https://developer.sportradar.com/basketball/reference/g-league-overview.   See if they have NBA data as well that might have some of what we are missing.   A good example you can look for is the Denver Nuggets player Spencer Jones.   He is on the roster in the data we have, but not listed in the contracts.  