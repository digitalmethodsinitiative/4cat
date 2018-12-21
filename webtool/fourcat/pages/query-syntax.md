## Query Syntax

4CAT supports advanced query syntax that you can use to make your search query
more precise, much like the syntax Google and other search engines support.

It is however tuned so that search queries are completed relatively quickly,
and this comes at the expense of accuracy in some edge cases; more posts may
be returned than match your query. In many cases, you can use the analytical 
post-processors available through 4CAT (such as the Exact Matches analysis) 
to further narrow down your results.

The following syntax is supported:

- `amsterdam netherlands` - Match posts containing both `amsterdam` and 
  `netherlands`

- `amsterdam | netherlands` - Match posts containing either `amsterdam` 
   or `netherlands`

- `"amsterdam netherlands"` - Match the phrase `amsterdam netherlands`, 
   occuring exactly like that

- `amsterdam -netherlands` - Match posts containing `amsterdam` but 
   not `netherlands`

- `amsterdam << netherlands` - Match posts containing `amsterdam` and 
  `netherlands`, with `amsterdam` occurring first

- `^amsterdam` - Match posts starting with `amsterdam`

- `netherlands$` - Match posts ending with `netherlands`

- `amsterd*m` - Match posts containing `amsterdam` or
  [`amsterdoom`](https://www.mobygames.com/game/amsterdoom/)

Note that for punctuation and non-alphanumeric characters, it is often 
necessary to wrap them in `"quotation marks"`; if not, they will be ignored
by the search engine. 

This is especially important to keep in mind when searching for URLs; if you
do not wrap these in quotation marks, their parts will be interpreted as 
separate words, e.g. `http://www.google.com` will be interpreted as a query for
posts containing `http`, `www`, `google` and `com` if not quoted. 
