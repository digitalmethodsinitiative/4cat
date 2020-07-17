# Usenet data source for 4CAT

This data source allows importing and searching archived Usenet messages.

Two archive formats are supported: mbox files and A News files.

Usenet's structure maps onto 4CAT terminology as follows:

- A group on Usenet corresponds to a board on 4CAT
- A thread of a message and its replies on Usenet corresponds to a 4CAT thread
- A message on Usenet corresponds to a 4CAT post 

## Principles

- A unique post is identified by its message ID
- Each post (i.e. each message ID) is only stored once
- A post may be part of different threads in different groups
- Per thread, one record is created with the ID [group]-[ID of first post]
- Links between threads and posts are recorded in a separate database table
- A message belongs to the thread matching its Reply-To header, or the thread
  matching the message matching its Reply-To header, et cetera
- A message belongs to at most one thread per group

## Caveats
- Message IDs may have been changed by the server receiving the message, in 
  which case multiple copies of the message may be stored