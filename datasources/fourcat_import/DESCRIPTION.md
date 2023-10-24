This data source allows importing datasets from other 4CAT servers. This can be
useful if you are doing work on several servers at once and want to move all
collected datasets to a central place, for example.

To import a dataset, you need to have access to it on its original server. You
additionally need an API token for that server, which you can generate via the
'API Access' link in the 4CAT navigation.

There are some caveats and limitations to consider:

* If an imported dataset was filtered from another dataset, the 'link' to the
  original dataset will not be retained on importing, and it will not be
  possible to see what dataset the imported, filtered dataset originated from.
* Datasets with empty data files are not imported. This includes datasets that
  did not complete successfully.
* It is not possible to anonymise or pseudonymise a dataset while importing it,
  though you can run anonymisation processors on the imported dataset 
  afterwards.
* The imported dataset will belong to you (the user importing it). If the 
  original dataset was shared with other people and/or tags, you will need to
  re-share it after importing.