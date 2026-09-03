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

4CAT finds those patterns by reading the post IDs of the public TikTok datasets on this server, most recent first, and
counting which patterns occur in them. Only video post IDs are used; users, comments and livestreams use the same ID
scheme but different patterns. An administrator can also fill in a fixed list of patterns in this data source's
settings, in which case that list is used instead and no datasets are read.

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
- **Most common machine IDs.** These bits identify the datacentre where the video was uploaded from. Steel et al. found they
  generally correlates with where a post comes from. Restricting them will skew which parts of the world end up in your dataset.
- **Most common ID patterns.** Only the most common ID patterns can be tested.

## What is recorded

The dataset log records the exact time range, the millisecond window, the machine IDs and the full list of ID patterns
used, so that a sample can be reproduced or checked.

It also records how many candidate IDs were requested and a breakdown of what TikTok said about the ones that did not
yield a post. That breakdown is what lets you estimate how many posts were originally made in the range, including
those that have since been deleted or made private — a number the collected posts alone cannot tell you.
