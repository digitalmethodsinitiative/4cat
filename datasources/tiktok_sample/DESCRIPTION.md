This TikTok data source collects a sample of everything that was posted to TikTok during a short time
range. This works on the basis of generating possible video IDs and requesting each one to see if they belong to an 
actual video. It draws from methods described by [Steel et al. (2026)](https://journalqd.org/article/view/9514).

## How it works

A TikTok post ID is a 64-bit number in which the first 32 bits are the UNIX timestamp of the second the post was created
and the next 10 bits are the millisecond within that second. The remaining 22 bits encode a counter, the type of entity the ID belongs to, and the ID of the machine that minted it. Only a
few hundred of the four million possible ID patterns are ever actually used.

If you know which ID patterns have occurred in previously collected videos, these can be used to fetch new videos as 
well. Steel et al. estimate that a good set of patterns covers well over 99% of the
posts made in a time range.

4CAT finds those patterns by reading the post IDs of the TikTok datasets on this server, most recent first, and
counting which patterns occur in them. Only video post IDs are used; users, comments and livestreams use the same ID
scheme but different patterns. This happens in the background, once when this 4CAT instance starts and daily after
that, so a query never waits for it — but it also means a brand new instance cannot sample until that has run once. An
administrator can also fill in a fixed list of patterns in this data source's settings, in which case that list is used
instead and no datasets are read.

Every TikTok dataset on the server is read, private ones included. What comes out of it is a property of TikTok's ID
scheme rather than of anyone's data: the timestamp bits are discarded, and no post, author or dataset of origin is
recorded. No single dataset may supply more than its share of the post IDs read, so the result describes the platform
rather than whichever collection happens to be newest.

While reading those post IDs, 4CAT also records which countries the posts said they were created in, per machine ID.
That is what the location-based selection below is built on. Most TikTok posts carry no location at all, so those
counts cover a minority of the posts read; the query form says what that minority is on this instance. Only the five
most common countries are listed per machine ID, and those are the ones a location selects it by.

Compiling ID patterns should not be static: TikTok's infrastructure changes over time, machines are added and retired, and a
pattern list that gave good coverage a year ago may miss part of the platform today.

## Hit rates

Fewer than one in a hundred candidate IDs corresponds to a post that ever existed, and only part of those can still be
retrieved. Expect a few thousand posts per million requests. One full second of TikTok is roughly half a million
candidate IDs. Steel et al. needed five months, spread over a cluster of machines, to collect 83 minutes of TikTok.

This means this data source is only really usable on a 4CAT instance with a *substantial pool of proxies* configured. The
time range that may be sampled and the number of candidate IDs per query are both capped.

### Improving hit rates at the cost of completeness

The following methods can be used to improve the hit rate, but they reduce the coverage of the sample:

- **Milliseconds per second.** The millisecond field of the ID is uniformly distributed, so sampling only the first
  *n* milliseconds of each second gives you an unbiased random subsample: at 100 milliseconds you collect roughly a
  tenth of the posts for a tenth of the requests. This is the setting to use if you want a smaller dataset that still
  represents the whole range.
- **Machine IDs.** The last six bits of a post ID identify the datacentre the video was uploaded to. Steel et al. found
  that this generally correlates with where a post comes from. Restricting them will skew which parts of the world end
  up in your dataset. They can be limited in three ways: by selecting locations, in which case every machine ID that
  has one of those countries among the five most common locations recorded for it is used; by taking the *n* machine
  IDs that minted the most known posts; or by writing a list of machine IDs by hand. Each option in the query form
  names the countries observed for the machines it selects, with their shares, so that what a narrower sample gives up
  is visible where it is chosen. Note that these shares describe the posts this 4CAT instance happens to have
  collected, which is not itself a sample of TikTok, and that a machine mints posts from all over: this narrows a
  sample towards a region rather than restricting it to one.
- **Most common ID patterns.** Every pattern costs the same number of requests per second sampled, but the rarest ones
  almost never correspond to a post that existed. Leaving them out therefore raises the hit rate and shortens the
  query, at the cost of the posts made through those patterns. The query form offers this as a coverage figure — the
  share of the posting known to this server that each setting still reaches — along with the number of patterns it
  uses and roughly what it does to the hit rate. Dropping the last percent of coverage typically saves a third of the
  requests; going much below 98% starts removing whole machine IDs rather than rare patterns, which skews the sample
  regionally in the same way that selecting machine IDs by hand does.

## What is recorded

The dataset log records the exact time range, the millisecond window, the machine IDs and the full list of ID patterns
used, so that a sample can be reproduced or checked.

It also records how many candidate IDs were requested and a breakdown of what TikTok said about the ones that did not
yield a post. That breakdown is what lets you estimate how many posts were originally made in the range, including
those that have since been deleted or made private — a number the collected posts alone cannot tell you.
