# Usenet data source for 4CAT

This data source allows importing and searching archived Usenet messages.

One way of acquiring data is available out of the box - with the script 
`import_usenet_posts.py` in `helper-scripts` in the 4CAT root folder you can
import any message databases created with 
[this script](https://github.com/stijn-uva/usenet-import).

Usenet's structure maps onto 4CAT terminology as follows:

- Groups are considered 'tags', analogous to hashtags, as a post can be posted
  in multiple groups. This means you can do e.g. a co-tag analysis based on 
  group links, useful for mapping the structure of a Usenet community.
- A thread of a message and its replies on Usenet corresponds to a 4CAT thread.
  Thread links are determined through recursive following of 'References' 
  headers in a message. If after this a message still has multiple 'References'
  IDs, the first one is considered canonical.
- A message on Usenet corresponds to a 4CAT post.

## Principles

- A unique post is identified by its message ID
- Each post (i.e. each message ID) is only stored once
- A post will only be linked to one thread in 4CAT, but as all headers are
  retained in the results no thread-level information is lost.
- Per thread, one record is created with the ID of the first message in that
  thread that is available.

## Caveats
- Message IDs may have been changed by the server receiving the message, in 
  which case multiple copies of the message may be stored