## Query Syntax for Local Data Sources

4CAT supports advanced query syntax for locally stored sources. These currently
include 4chan, 8chan, and Breitbart. This can be used to make queries more
precise, much like the syntax Google and other search engines support.

It is however tuned so that search queries are completed relatively quickly,
and this comes at the expense of accuracy in some edge cases; more posts may
be returned than match your query. In many cases, you can use the analytical 
post-processors available through 4CAT (such as the Exact Matches analysis) 
to further narrow down your results.

Note that many of 4CAT's sources use external APIs to collect data, and text search
is handled through their API parameters. This means those searches function differently
compared to 4CAT's own text search functions as described on this page. Puhshift's
Reddit search, for instance, will have different syntax.

The following syntax is supported:

- `amsterdam netherlands` - Match posts containing both `amsterdam` and 
  `netherlands`

- `amsterdam | netherlands` - Match posts containing either `amsterdam` 
   or `netherlands` (or both)

- `"amsterdam netherlands"` - Match the phrase `amsterdam netherlands`, 
   occurring exactly like that.

- `amsterdam -netherlands` - Match posts containing `amsterdam` but 
   not `netherlands`

- `amsterdam << netherlands` - Match posts containing `amsterdam` and 
  `netherlands`, with `amsterdam` occurring first

- `^amsterdam` - Match posts starting with `amsterdam`

- `netherlands$` - Match posts ending with `netherlands`

- `amsterd*m` - Match posts containing `amsterdam` or
  [`amsterdoom`](https://www.mobygames.com/game/amsterdoom/)

- `netherlands (amsterdam | rotterdam)` - Match posts containing `netherlands`
  and either `amsterdam` or `rotterdam` (or both)

Note that for punctuation and non-alphanumeric characters, it is often 
necessary to wrap them in `"quotation marks"`; if not, they will be ignored
by the search engine. 

This is especially important to keep in mind when searching for URLs; if you
do not wrap these in quotation marks, their parts will be interpreted as 
separate words, e.g. `http://www.google.com` will be interpreted as a query for
posts containing `http`, `www`, `google` and `com` if not quoted. 
